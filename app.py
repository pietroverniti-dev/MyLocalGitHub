import os
import mimetypes
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session, jsonify
from markupsafe import Markup
import markdown
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import HtmlFormatter
import time

app = Flask(__name__)
# Chiave segreta per le sessioni, essenziale per la sicurezza.
app.secret_key = 'la_tua_password_segreta_qui'

# La variabile globale per il percorso del repository.
REPO_BASE_PATH = None

# Sicurezza: limita i tentativi di accesso per prevenire attacchi a forza bruta.
MAX_ATTEMPTS = 5
COOLDOWN_TIME = 300 # Tempo di blocco in secondi (5 minuti)
login_attempts = {} # Dizionario per tracciare gli IP e i loro tentativi

def get_password():
    """Legge la password da un file esterno per evitare di scriverla nel codice."""
    try:
        with open("password.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
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
                login_attempts[ip_address] = (0, time.time())
    else:
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
        
        # Incrementa i tentativi falliti.
        login_attempts[request.remote_addr] = (login_attempts[request.remote_addr][0] + 1, time.time())

        # Verifica la password dal file esterno.
        if user_password == get_password():
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
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
@app.route('/<path:subpath>', methods=['GET', 'POST'])
def view_repo(subpath=''):
    """
    Gestisce la visualizzazione del repository.
    """
    global REPO_BASE_PATH
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        user_path = request.form.get('repo_path')
        if not user_path:
            return "<h1>Errore: Nessun percorso fornito.</h1>", 400
        
        normalized_path = os.path.normpath(user_path)
        if not os.path.isdir(normalized_path):
            return f"<h1>Errore: '{normalized_path}' non è una directory valida.</h1>", 404
        
        REPO_BASE_PATH = normalized_path
        return redirect(url_for('view_repo', subpath=''))

    if REPO_BASE_PATH is None:
        return render_template('index.html', view_type='form')

    full_path = os.path.join(REPO_BASE_PATH, subpath)

    if not os.path.normpath(full_path).startswith(os.path.normpath(REPO_BASE_PATH)):
        return "<h1>Errore di sicurezza: Tentativo di accesso non autorizzato.</h1>", 403
        
    if os.path.isfile(full_path):
        return display_file(full_path, subpath)
    
    if os.path.isdir(full_path):
        return browse_directory(full_path, subpath, REPO_BASE_PATH)
    
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
                    readme_html = Markup(markdown.markdown(readme_content, extensions=['tables', 'toc']))
            except Exception as e:
                readme_html = f"Errore durante la lettura del file README.md: {e}"

        for item_name in sorted(os.listdir(path)):
            if item_name.startswith('.'):
                continue
            
            full_item_path = os.path.join(path, item_name)
            item_type = 'dir' if os.path.isdir(full_item_path) else 'file'
            icon = 'folder' if item_type == 'dir' else 'file'
            
            relative_path = os.path.relpath(full_item_path, base_path)
            items.append({
                'name': item_name,
                'type': item_type,
                'url_path': relative_path,
                'icon': icon
            })
            
        return render_template('index.html', 
                                view_type='browser',
                                items=items, 
                                current_subpath=subpath,
                                readme_html=readme_html,
                                REPO_BASE_PATH=base_path)
                                
    except PermissionError:
        return f"<h1>Errore di permessi: Non hai accesso a '{path}'.</h1>", 403

def display_file(path, subpath):
    """Gestisce la visualizzazione di un singolo file."""
    try:
        _, file_extension = os.path.splitext(path)
        
        if file_extension.lower() == '.pdf':
            relative_path = os.path.relpath(path, REPO_BASE_PATH)
            return redirect(url_for('serve_file', filename=relative_path))
        
        text_file_extensions = {
            '.txt', '.py', '.html', '.css', '.js', '.json', '.md', '.log', '.xml',
            '.c', '.cpp', '.java', '.go', '.rs', '.php', '.sh', '.rb', '.pl', '.tex'
        }
        is_text_file = file_extension.lower() in text_file_extensions or 'text' in (mimetypes.guess_type(path)[0] or '')

        if is_text_file:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            try:
                lexer = guess_lexer(content)
                formatter = HtmlFormatter(style='default', lineanchors='line')
                content = highlight(content, lexer, formatter)
            except Exception:
                content = f"<pre>{Markup.escape(content)}</pre>"
        else:
            content = "Questo tipo di file non può essere visualizzato come testo."
        
        return render_template('index.html',
                               view_type='viewer',
                               file_name=os.path.basename(path),
                               content=Markup(content),
                               is_text_file=is_text_file)
                                
    except Exception as e:
        return f"<h1>Errore durante la lettura del file:</h1><p>{e}</p>", 500

@app.route('/serve/<path:filename>')
def serve_file(filename):
    """Serve un file statico direttamente al browser."""
    global REPO_BASE_PATH
    if not REPO_BASE_PATH:
        return "<h1>Errore: Repository non impostato.</h1>", 500

    full_path = os.path.join(REPO_BASE_PATH, filename)
    
    if not os.path.normpath(full_path).startswith(os.path.normpath(REPO_BASE_PATH)):
        return "<h1>Errore di sicurezza: Tentativo di accesso non autorizzato.</h1>", 403
    
    directory = os.path.dirname(full_path)
    file_name = os.path.basename(full_path)
    
    return send_from_directory(directory, file_name, as_attachment=False)

if __name__ == '__main__':
    app.run(debug=True)
