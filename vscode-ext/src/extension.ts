import * as vscode from 'vscode';
import * as http from 'http';
import { SidebarProvider } from './sidebarProvider';

export function activate(context: vscode.ExtensionContext) {
    console.log('LocoEngine AI Extension is now active!');

    const sidebarProvider = new SidebarProvider(context.extensionUri);
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(
            'loco-sidebar-view',
            sidebarProvider
        )
    );

    // Synchronize workspace folder with the engine backend
    const syncWorkspace = () => {
        const syncEnabled = vscode.workspace.getConfiguration('locoengine').get('enableWorkspaceSync', true);
        if (!syncEnabled) {
            return;
        }

        const workspaceFolders = vscode.workspace.workspaceFolders;
        if (workspaceFolders && workspaceFolders.length > 0) {
            const workspacePath = workspaceFolders[0].uri.fsPath;
            console.log(`Syncing workspace path to LocoEngine: ${workspacePath}`);
            
            const serverUrl = vscode.workspace.getConfiguration('locoengine').get('serverUrl', 'http://127.0.0.1:8000');
            let host = '127.0.0.1';
            let port = 8000;
            
            try {
                const url = new URL(serverUrl);
                host = url.hostname || '127.0.0.1';
                port = parseInt(url.port) || 80;
            } catch (e) {
                // fall back to default
            }

            const postData = JSON.stringify({ workspace_dir: workspacePath });
            const req = http.request({
                hostname: host,
                port: port,
                path: '/api/config',
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Content-Length': Buffer.byteLength(postData)
                }
            }, (res) => {
                let body = '';
                res.on('data', chunk => body += chunk);
                res.on('end', () => {
                    console.log(`LocoEngine workspace sync response: ${res.statusCode} - ${body}`);
                });
            });

            req.on('error', (err) => {
                console.error(`Failed to sync workspace path to LocoEngine: ${err.message}`);
            });

            req.write(postData);
            req.end();
        }
    };

    // Run sync on startup
    syncWorkspace();

    // Run sync when folders change
    context.subscriptions.push(
        vscode.workspace.onDidChangeWorkspaceFolders(() => syncWorkspace())
    );

    // Focus chat sidebar command
    context.subscriptions.push(
        vscode.commands.registerCommand('locoengine.focusSidebar', () => {
            vscode.commands.executeCommand('loco-sidebar-view.focus');
        })
    );

    // Add selected text to chat sidebar
    context.subscriptions.push(
        vscode.commands.registerCommand('locoengine.addSelectionToChat', () => {
            const editor = vscode.window.activeTextEditor;
            if (!editor) {
                vscode.window.showInformationMessage('No active editor to copy selection from.');
                return;
            }

            const selection = editor.selection;
            const text = editor.document.getText(selection);
            if (!text.trim()) {
                vscode.window.showInformationMessage('Selected text is empty.');
                return;
            }

            sidebarProvider.sendSelectionToWebview(text, editor.document.fileName);
            // Focus the view
            vscode.commands.executeCommand('loco-sidebar-view.focus');
        })
    );
}

export function deactivate() {}
