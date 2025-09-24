import os
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from markupsafe import Markup
import markdown
from pygments import highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import HtmlFormatter
import mimetypes

app = Flask(__name__)

REPO_BASE_PATH = None

@app.template_filter('dirname')
def dirname_filter(s):
    return os.path.dirname(s)

@app.route('/', methods=['GET', 'POST'])
@app.route('/<path:subpath>', methods=['GET', 'POST'])
def view_repo(subpath=''):
    global REPO_BASE_PATH

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

    current_full_path = os.path.join(REPO_BASE_PATH, subpath)

    if not os.path.normpath(current_full_path).startswith(os.path.normpath(REPO_BASE_PATH)):
        return "<h1>Errore di sicurezza: Tentativo di accesso non autorizzato.</h1>", 403
        
    if os.path.isfile(current_full_path):
        return display_file(current_full_path)
    
    if not os.path.isdir(current_full_path):
        return f"<h1>Errore: Il percorso '{subpath}' non è stato trovato.</h1>", 404

    return browse_directory(current_full_path, subpath, REPO_BASE_PATH)

def browse_directory(path, subpath, base_path):
    try:
        items = []
        readme_html = None
        
        readme_path = os.path.join(path, 'README.md')
        if os.path.exists(readme_path):
            try:
                with open(readme_path, 'r', encoding='utf-8', errors='ignore') as f:
                    readme_content = f.read()
                    readme_html = Markup(markdown.markdown(readme_content))
            except Exception as e:
                readme_html = f"Errore durante la lettura del file README.md: {e}"

        for item_name in sorted(os.listdir(path)):
            if item_name.startswith('.'):
                continue
            
            full_path = os.path.join(path, item_name)
            item_type = 'dir' if os.path.isdir(full_path) else 'file'
            icon = 'folder' if item_type == 'dir' else 'file'
            
            relative_path = os.path.relpath(full_path, base_path)
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

@app.route('/download/<path:filename>')
def download_file(filename):
    """Serve il file statico al browser."""
    # Assicura che il file richiesto si trovi all'interno del REPO_BASE_PATH per motivi di sicurezza
    full_path = os.path.join(REPO_BASE_PATH, filename)
    if not os.path.normpath(full_path).startswith(os.path.normpath(REPO_BASE_PATH)):
        return "<h1>Errore di sicurezza: Tentativo di accesso non autorizzato.</h1>", 403
    
    directory = os.path.dirname(full_path)
    file_name = os.path.basename(full_path)
    
    return send_from_directory(directory, file_name)

def display_file(path):
    try:
        _, file_extension = os.path.splitext(path)
        
        is_pdf = file_extension.lower() == '.pdf'
        if is_pdf:
            relative_path = os.path.relpath(path, REPO_BASE_PATH)
            return redirect(url_for('download_file', filename=relative_path))

        text_file_extensions = {
            '.txt', '.py', '.html', '.css', '.js', '.json', '.md', '.log', '.xml',
            '.c', '.cpp', '.java', '.go', '.rs', '.php', '.sh', '.rb', '.pl'
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
        
        return render_template('index.html',
                                view_type='viewer',
                                file_name=os.path.basename(path),
                                content=Markup(content),
                                is_text_file=is_text_file)
                                
    except Exception as e:
        return f"<h1>Errore durante la lettura del file:</h1><p>{e}</p>", 500

if __name__ == '__main__':
    app.run(debug=True)