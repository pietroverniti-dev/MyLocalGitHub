import os
import mimetypes
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from markupsafe import Markup
import markdown
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import HtmlFormatter

app = Flask(__name__)

# La variabile globale per il percorso del repository.
REPO_BASE_PATH = None

# Registro un filtro Jinja2 personalizzato per ottenere il nome della directory padre.
@app.template_filter('dirname')
def dirname_filter(s):
    return os.path.dirname(s)

@app.route('/', methods=['GET', 'POST'])
@app.route('/<path:subpath>', methods=['GET', 'POST'])
def view_repo(subpath=''):
    """
    Gestisce la visualizzazione del repository, distinguendo tra:
    1. Input del percorso iniziale (POST).
    2. Navigazione tra cartelle e file (GET).
    """
    global REPO_BASE_PATH

    # Gestisce il form di input del percorso
    if request.method == 'POST':
        user_path = request.form.get('repo_path')
        if not user_path:
            return "<h1>Errore: Nessun percorso fornito.</h1>", 400
        
        normalized_path = os.path.normpath(user_path)
        if not os.path.isdir(normalized_path):
            return f"<h1>Errore: '{normalized_path}' non è una directory valida.</h1>", 404
        
        REPO_BASE_PATH = normalized_path
        return redirect(url_for('view_repo', subpath=''))

    # Se non è stato impostato un percorso, mostra il form
    if REPO_BASE_PATH is None:
        return render_template('index.html', view_type='form')

    # Costruisce il percorso completo e valido
    full_path = os.path.join(REPO_BASE_PATH, subpath)

    # Controllo di sicurezza contro l'attacco di tipo directory traversal
    if not os.path.normpath(full_path).startswith(os.path.normpath(REPO_BASE_PATH)):
        return "<h1>Errore di sicurezza: Tentativo di accesso non autorizzato.</h1>", 403
        
    # Reindirizza alla funzione di visualizzazione appropriata
    if os.path.isfile(full_path):
        return display_file(full_path, subpath)
    
    if os.path.isdir(full_path):
        return browse_directory(full_path, subpath, REPO_BASE_PATH)
    
    # Gestisce il caso in cui il percorso non esiste
    return f"<h1>Errore: Il percorso '{subpath}' non è stato trovato.</h1>", 404

def browse_directory(path, subpath, base_path):
    """
    Visualizza il contenuto di una cartella, inclusi i file e la README.
    """
    try:
        items = []
        readme_html = None
        
        readme_path = os.path.join(path, 'README.md')
        if os.path.exists(readme_path) and os.path.isfile(readme_path):
            try:
                with open(readme_path, 'r', encoding='utf-8', errors='ignore') as f:
                    readme_content = f.read()
                    # Converte il Markdown in HTML con l'estensione 'toc' per i link interni
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
    """
    Gestisce la visualizzazione di un singolo file, reindirizzando per i formati non testuali
    o visualizzando il contenuto per i file di testo.
    """
    try:
        _, file_extension = os.path.splitext(path)
        
        # Gestisce i file che devono essere aperti/scaricati dal browser (es. PDF, immagini, ecc.).
        if file_extension.lower() == '.pdf':
            relative_path = os.path.relpath(path, REPO_BASE_PATH)
            return redirect(url_for('serve_file', filename=relative_path))
        
        # Elenco dei tipi di file di testo supportati per la visualizzazione
        text_file_extensions = {
            '.txt', '.py', '.html', '.css', '.js', '.json', '.md', '.log', '.xml',
            '.c', '.cpp', '.java', '.go', '.rs', '.php', '.sh', '.rb', '.pl', '.tex'  # <--- Aggiunta l'estensione .tex
        }
        is_text_file = file_extension.lower() in text_file_extensions or 'text' in (mimetypes.guess_type(path)[0] or '')

        if is_text_file:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            try:
                # Evidenzia la sintassi del codice
                lexer = guess_lexer(content)
                formatter = HtmlFormatter(style='default', lineanchors='line')
                content = highlight(content, lexer, formatter)
            except Exception:
                # Se l'evidenziazione fallisce, mostra il testo normale
                content = f"<pre>{Markup.escape(content)}</pre>"
        else:
            # Se il file non è di testo e non è un PDF, informa l'utente
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
    """
    Serve un file statico direttamente al browser.
    """
    global REPO_BASE_PATH
    if not REPO_BASE_PATH:
        return "<h1>Errore: Repository non impostato.</h1>", 500

    full_path = os.path.join(REPO_BASE_PATH, filename)
    
    # Altro controllo di sicurezza
    if not os.path.normpath(full_path).startswith(os.path.normpath(REPO_BASE_PATH)):
        return "<h1>Errore di sicurezza: Tentativo di accesso non autorizzato.</h1>", 403
    
    directory = os.path.dirname(full_path)
    file_name = os.path.basename(full_path)
    
    return send_from_directory(directory, file_name, as_attachment=False)

if __name__ == '__main__':
    app.run(debug=True)
