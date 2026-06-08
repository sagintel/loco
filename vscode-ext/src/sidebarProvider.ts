import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';

export class SidebarProvider implements vscode.WebviewViewProvider {
    private _view?: vscode.WebviewView;

    constructor(private readonly _extensionUri: vscode.Uri) {}

    public resolveWebviewView(
        webviewView: vscode.WebviewView,
        context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken
    ) {
        this._view = webviewView;

        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this._extensionUri]
        };

        webviewView.webview.html = this._getHtmlForWebview(webviewView.webview);

        // Listen to messages from the webview
        webviewView.webview.onDidReceiveMessage(async (data) => {
            switch (data.type) {
                case 'getWorkspaceContext': {
                    const workspaceFolders = vscode.workspace.workspaceFolders;
                    const folderName = workspaceFolders && workspaceFolders.length > 0 ? workspaceFolders[0].name : '';
                    const folderPath = workspaceFolders && workspaceFolders.length > 0 ? workspaceFolders[0].uri.fsPath : '';
                    
                    const editor = vscode.window.activeTextEditor;
                    let activeFile = '';
                    let selectedText = '';
                    if (editor) {
                        activeFile = folderPath ? path.relative(folderPath, editor.document.fileName) : editor.document.fileName;
                        selectedText = editor.document.getText(editor.selection);
                    }
                    
                    webviewView.webview.postMessage({
                        type: 'workspaceContext',
                        folderName,
                        folderPath,
                        activeFile,
                        selectedText
                    });
                    break;
                }
                case 'openFile': {
                    const workspaceFolders = vscode.workspace.workspaceFolders;
                    const folderPath = workspaceFolders && workspaceFolders.length > 0 ? workspaceFolders[0].uri.fsPath : '';
                    const fullPath = path.isAbsolute(data.path) 
                        ? data.path 
                        : path.join(folderPath, data.path);
                        
                    if (fs.existsSync(fullPath)) {
                        vscode.workspace.openTextDocument(fullPath).then(doc => {
                            vscode.window.showTextDocument(doc);
                        });
                    } else {
                        vscode.window.showErrorMessage(`File not found: ${data.path}`);
                    }
                    break;
                }
                case 'insertSnippet': {
                    const editor = vscode.window.activeTextEditor;
                    if (editor) {
                        editor.edit(editBuilder => {
                            editBuilder.insert(editor.selection.active, data.code);
                        });
                    } else {
                        vscode.window.showErrorMessage('No active text editor to insert code snippet into.');
                    }
                    break;
                }
                case 'getSettings': {
                    const config = vscode.workspace.getConfiguration('locoengine');
                    webviewView.webview.postMessage({
                        type: 'settings',
                        serverUrl: config.get('serverUrl', 'http://127.0.0.1:8000')
                    });
                    break;
                }
                case 'saveSettings': {
                    const config = vscode.workspace.getConfiguration('locoengine');
                    await config.update('serverUrl', data.serverUrl, vscode.ConfigurationTarget.Global);
                    vscode.window.showInformationMessage('LocoEngine settings saved.');
                    break;
                }
                case 'showErrorMessage': {
                    vscode.window.showErrorMessage(data.message);
                    break;
                }
                case 'showInfoMessage': {
                    vscode.window.showInformationMessage(data.message);
                    break;
                }
            }
        });

        // Listen for active editor changes to sync context header
        const editorChangeSubscription = vscode.window.onDidChangeActiveTextEditor(editor => {
            if (this._view) {
                const workspaceFolders = vscode.workspace.workspaceFolders;
                const folderPath = workspaceFolders && workspaceFolders.length > 0 ? workspaceFolders[0].uri.fsPath : '';
                let activeFile = '';
                let selectedText = '';
                
                if (editor) {
                    activeFile = folderPath ? path.relative(folderPath, editor.document.fileName) : editor.document.fileName;
                    selectedText = editor.document.getText(editor.selection);
                }
                
                this._view.webview.postMessage({
                    type: 'activeEditorChanged',
                    activeFile,
                    selectedText
                });
            }
        });

        // Listen for text selection changes to update selection context
        const selectionChangeSubscription = vscode.window.onDidChangeTextEditorSelection(event => {
            if (this._view && event.textEditor === vscode.window.activeTextEditor) {
                const workspaceFolders = vscode.workspace.workspaceFolders;
                const folderPath = workspaceFolders && workspaceFolders.length > 0 ? workspaceFolders[0].uri.fsPath : '';
                const activeFile = folderPath ? path.relative(folderPath, event.textEditor.document.fileName) : event.textEditor.document.fileName;
                const selectedText = event.textEditor.document.getText(event.selections[0]);
                
                this._view.webview.postMessage({
                    type: 'activeEditorChanged',
                    activeFile,
                    selectedText
                });
            }
        });

        webviewView.onDidDispose(() => {
            editorChangeSubscription.dispose();
            selectionChangeSubscription.dispose();
        });
    }

    public sendSelectionToWebview(text: string, filePath: string) {
        if (this._view) {
            const workspaceFolders = vscode.workspace.workspaceFolders;
            const folderPath = workspaceFolders && workspaceFolders.length > 0 ? workspaceFolders[0].uri.fsPath : '';
            const relPath = folderPath ? path.relative(folderPath, filePath) : filePath;
            
            this._view.webview.postMessage({
                type: 'addSelection',
                text,
                filePath: relPath
            });
        }
    }

    private _getHtmlForWebview(webview: vscode.Webview): string {
        const htmlPath = path.join(this._extensionUri.fsPath, 'src', 'webview.html');
        let html = '';
        try {
            html = fs.readFileSync(htmlPath, 'utf8');
        } catch (err) {
            return `<html><body><h3>Failed to load UI files. Ensure extension is compiled correctly.</h3><p>${err}</p></body></html>`;
        }

        // Get resource paths
        const cssUri = webview.asWebviewUri(vscode.Uri.file(path.join(this._extensionUri.fsPath, 'src', 'webview.css')));
        const jsUri = webview.asWebviewUri(vscode.Uri.file(path.join(this._extensionUri.fsPath, 'src', 'webview.js')));
        
        // Generate nonces
        const nonce = getNonce();

        // Replace placeholders
        html = html
            .replace(/\{\{WEBVIEW_CSS_URI\}\}/g, cssUri.toString())
            .replace(/\{\{WEBVIEW_JS_URI\}\}/g, jsUri.toString())
            .replace(/\{\{CSP_NONCE\}\}/g, nonce);

        return html;
    }
}

function getNonce() {
    let text = '';
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    for (let i = 0; i < 32; i++) {
        text += possible.charAt(Math.floor(Math.random() * possible.length));
    }
    return text;
}
