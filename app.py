# -*- coding: utf-8 -*-
import os
import mimetypes
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session
from markupsafe import Markup
from markdown import markdown
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import HtmlFormatter
from pygments.styles import get_style_by_name
import time

app = Flask(__name__)
# Chiave segreta per le sessioni. Usare una chiave complessa e casuale.
app.secret_key = 'chiave_segreta_molto_difficile_e_lunga_e_casuale'

# Sicurezza: limita i tentativi di accesso per prevenire attacchi a forza bruta.
MAX_ATTEMPTS = 5
COOLDOWN_TIME = 300 # 5 minuti in secondi
login_attempts = {}

def get_password():
    """
    Legge la password da un file esterno per evitare di scriverla nel codice.
    Assicurati che il file password.txt esista nella stessa directory dell'app.
    """
    try:
        with open("password.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        print("Errore: File 'password.txt' non trovato. Crea il file e inserisci la password.")
        return None

def check_brute_force():
    """Verifica se l'IP ha superato il limite di tentativi di accesso."""
    ip_address = request.remote_addr
    if ip_address in login_attempts:
        attempts, last_attempt_time = login_attempts[ip_address]
        if attempts >= MAX_ATTEMPTS:
            elapsed_time = time.time() - last_attempt_time
            if elapsed_time < COOLDOWN_TIME:
                return False, f"Troppi tentativi di accesso. Riprova tra {int(COOLDOWN_TIME - elapsed_time)} secondi."
            else:
                # Resetta i tentativi dopo il tempo di cooldown
                login_attempts[ip_address] = (0, time.time())
    else:
        # Inizializza i tentativi per il nuovo IP
        login_attempts[ip_address] = (0, time.time())
    return True, None

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Gestisce la logica di accesso tramite password."""
    is_ok_to_try, error_message = check_brute_force()
    if not is_ok_to_try:
        return render_template('login.html', error=error_message)

    if request.method == 'POST':
        user_password = request.form.get('password')
        
        # Incrementa i tentativi prima di controllare la password
        current_attempts, _ = login_attempts[request.remote_addr]
        login_attempts[request.remote_addr] = (current_attempts + 1, time.time())

        # Verifica la password dal file esterno.
        correct_password = get_password()
        if correct_password and user_password == correct_password:
            session['logged_in'] = True
            # Cancella i tentativi falliti dopo un accesso riuscito.
            if request.remote_addr in login_attempts:
                del login_attempts[request.remote_addr]
            return redirect(url_for('view_repo'))
        else:
            return render_template('login.html', error="Password errata.")
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """Gestisce la disconnessione dell'utente."""
    session.pop('logged_in', None)
    session.pop('repo_path', None)
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
@app.route('/<path:subpath>', methods=['GET', 'POST'])
def view_repo(subpath=''):
    """Gestisce la visualizzazione del repository e il reindirizzamento."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
        
    repo_base_path = session.get('repo_path')

    if request.method == 'POST':
        user_path = request.form.get('repo_path')
        if not user_path:
            return "<h1>Errore: Nessun percorso fornito.</h1>", 400
        
        # Normalizza e valida il percorso
        normalized_path = os.path.normpath(user_path)
        if not os.path.isdir(normalized_path):
            return render_template('index.html', view_type='form', error=f"Errore: '{normalized_path}' non è una directory valida.")
        
        # Salva il percorso nella sessione
        session['repo_path'] = normalized_path
        return redirect(url_for('view_repo', subpath=''))

    if repo_base_path is None:
        return render_template('index.html', view_type='form')

    # Costruisci il percorso completo e valida la navigazione
    full_path = os.path.join(repo_base_path, subpath)
    
    # Assicurati che l'utente non possa navigare al di fuori della cartella base
    if not os.path.abspath(full_path).startswith(os.path.abspath(repo_base_path)):
        return "<h1>Errore di sicurezza: Tentativo di accesso non autorizzato.</h1>", 403
    
    if os.path.isfile(full_path):
        return display_file(full_path, subpath, repo_base_path)
    
    if os.path.isdir(full_path):
        return browse_directory(full_path, subpath, repo_base_path)
    
    return f"<h1>Errore: Il percorso '{subpath}' non è stato trovato.</h1>", 404

def browse_directory(path, subpath, base_path):
    """Visualizza il contenuto di una cartella, inclusi i file e la README."""
    try:
        items = []
        readme_html = None
        
        readme_path = os.path.join(path, 'README.md')
        if os.path.exists(readme_path) and os.path.isfile(readme_path):
            try:
                with open(readme_path, 'r', encoding='utf-8', errors='ignore') as f:
                    readme_content = f.read()
                    readme_html = Markup(markdown(readme_content, extensions=['fenced_code', 'tables', 'toc']))
            except Exception as e:
                readme_html = f"Errore durante la lettura del file README.md: {e}"

        for item_name in sorted(os.listdir(path)):
            if item_name.startswith('.'):
                continue
            
            full_item_path = os.path.join(path, item_name)
            item_type = 'dir' if os.path.isdir(full_item_path) else 'file'
            
            relative_path = os.path.relpath(full_item_path, base_path)
            
            _, ext = os.path.splitext(item_name)
            
            items.append({
                'name': item_name,
                'type': item_type,
                'url_path': relative_path.replace(os.sep, '/'),
                'ext': ext.lower()
            })

        # Prepara i dati per i breadcrumb
        breadcrumb_parts = []
        current_link = ''
        if subpath:
            path_parts = subpath.split('/')
            for part in path_parts:
                current_link = os.path.join(current_link, part)
                breadcrumb_parts.append({
                    'name': part,
                    'url_path': current_link.replace(os.sep, '/')
                })
        
        parent_path = os.path.dirname(subpath).replace(os.sep, '/') if subpath else None
        
        return render_template('index.html', 
                               view_type='browser',
                               items=items, 
                               current_subpath=subpath,
                               repo_base_path=base_path,
                               readme_html=readme_html,
                               breadcrumb_parts=breadcrumb_parts,
                               parent_path=parent_path)
    except PermissionError:
        return f"<h1>Errore di permessi: Non hai accesso a '{path}'.</h1>", 403

def display_file(path, subpath, base_path):
    """Gestisce la visualizzazione di un singolo file."""
    try:
        _, file_extension = os.path.splitext(path)
        
        # Reindirizza per i PDF
        if file_extension.lower() == '.pdf':
            return redirect(url_for('serve_file', filename=subpath))
        
        # Controlla se il file è un file di testo leggibile
        text_file_extensions = {
            '.txt', '.py', '.html', '.css', '.js', '.json', '.md', '.log', '.xml',
            '.c', '.cpp', '.java', '.go', '.rs', '.php', '.sh', '.rb', '.pl', '.tex'
        }
        is_text_file = file_extension.lower() in text_file_extensions or 'text' in (mimetypes.guess_type(path)[0] or '')

        content = ""
        if is_text_file:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                file_content = f.read()
            
            # Evidenziazione sintattica del codice
            pygments_style = get_style_by_name('nord')
            formatter = HtmlFormatter(style=pygments_style, lineanchors='line', cssclass='highlight')
            
            if file_extension.lower() == '.md':
                content = markdown(file_content, extensions=['fenced_code', 'tables'])
            else:
                try:
                    lexer = guess_lexer(file_content)
                    content = highlight(file_content, lexer, formatter)
                except Exception:
                    content = f"<pre>{Markup.escape(file_content)}</pre>"
        else:
            content = "Questo tipo di file non può essere visualizzato come testo."
        
        parent_path = os.path.dirname(subpath).replace(os.sep, '/')
        
        return render_template('index.html',
                               view_type='viewer',
                               file_name=os.path.basename(path),
                               content=Markup(content),
                               is_text_file=is_text_file,
                               pygments_style=formatter.get_style_defs('.highlight'),
                               parent_path=parent_path)
                                
    except Exception as e:
        return f"<h1>Errore durante la lettura del file:</h1><p>{e}</p>", 500

@app.route('/serve/<path:filename>')
def serve_file(filename):
    """Serve un file statico direttamente al browser, con controllo di sicurezza aggiuntivo."""
    repo_base_path = session.get('repo_path')
    if not repo_base_path:
        return "<h1>Errore: Repository non impostato.</h1>", 500

    full_path = os.path.join(repo_base_path, filename)
    
    # Valida il percorso per prevenire attacchi di directory traversal
    if not os.path.abspath(full_path).startswith(os.path.abspath(repo_base_path)):
        return "<h1>Errore di sicurezza: Tentativo di accesso non autorizzato.</h1>", 403

    if not os.path.exists(full_path):
        return f"<h1>Errore: Il file '{filename}' non è stato trovato.</h1>", 404

    try:
        directory = os.path.dirname(full_path)
        file_name = os.path.basename(full_path)
        
        return send_from_directory(directory, file_name, as_attachment=False)
    except Exception as e:
        return f"<h1>Errore durante il servizio del file:</h1><p>{e}</p>", 500

if __name__ == '__main__':
    # La modalità debug è utile solo in fase di sviluppo.
    # Disabilitala in produzione per motivi di sicurezza.
    app.run(debug=True)
