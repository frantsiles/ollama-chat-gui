
/**
 * Utility functions for the chat application
 */

const Utils = {
    /**
     * Debug logger with timestamps
     */
    log(category, message, data = null) {
        const timestamp = new Date().toISOString().split('T')[1].split('.')[0];
        const prefix = `[${timestamp}] [${category}]`;
        if (data) {
            console.log(prefix, message, data);
        } else {
            console.log(prefix, message);
        }
    },

    /**
     * Generate a unique ID
     */
    generateId() {
        return Math.random().toString(36).substring(2, 10);
    },

    /**
     * Escape HTML to prevent XSS
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    /**
     * Markdown parser with GFM table support (inspired by Warp's gfm_table.rs)
     */
    parseMarkdown(text) {
        if (!text) return '';

        // --- Phase 1: extract fenced code blocks to protect them ---
        const codeBlocks = [];
        let src = text.replace(/```([\w.-]*)\r?\n([\s\S]*?)```/g, (_, lang, code) => {
            const idx = codeBlocks.length;
            codeBlocks.push({ lang: lang || '', code });
            return `\x02CODE${idx}\x03`;
        });

        // --- Phase 2: extract inline code ---
        const inlineCodes = [];
        src = src.replace(/`([^`\n]+)`/g, (_, code) => {
            const idx = inlineCodes.length;
            inlineCodes.push(Utils.escapeHtml(code));
            return `\x02INLINE${idx}\x03`;
        });

        // --- Phase 3: escape HTML on the rest ---
        src = Utils.escapeHtml(src);

        // --- Phase 4: line-by-line pass (headers, tables, lists, hr, blockquote) ---
        const lines = src.split('\n');
        const out = [];
        let listType = null;   // 'ul' | 'ol' | null

        const flushList = () => {
            if (listType) { out.push(`</${listType}>`); listType = null; }
        };

        let i = 0;
        while (i < lines.length) {
            const line = lines[i];

            // Headings
            let m;
            if ((m = line.match(/^#{1,6} (.+)$/))) {
                const level = line.match(/^(#+)/)[1].length;
                flushList();
                out.push(`<h${level}>${m[1]}</h${level}>`);
                i++; continue;
            }

            // Horizontal rule
            if (/^(\*{3,}|-{3,}|_{3,})$/.test(line.trim())) {
                flushList(); out.push('<hr>'); i++; continue;
            }

            // Blockquote
            if (line.startsWith('&gt;')) {
                flushList();
                out.push(`<blockquote>${line.slice(4).trim()}</blockquote>`);
                i++; continue;
            }

            // GFM table: header row followed by separator row
            if (line.includes('|') && i + 1 < lines.length && _isGfmSeparator(lines[i + 1])) {
                flushList();
                const tableLines = [line, lines[i + 1]];
                i += 2;
                while (i < lines.length && lines[i].includes('|')) {
                    tableLines.push(lines[i++]);
                }
                out.push(_renderGfmTable(tableLines));
                continue;
            }

            // Unordered list
            if ((m = line.match(/^(\s*)[-*+] (.+)$/))) {
                if (listType !== 'ul') { flushList(); out.push('<ul>'); listType = 'ul'; }
                out.push(`<li>${m[2]}</li>`);
                i++; continue;
            }

            // Ordered list
            if ((m = line.match(/^\d+\. (.+)$/))) {
                if (listType !== 'ol') { flushList(); out.push('<ol>'); listType = 'ol'; }
                out.push(`<li>${m[1]}</li>`);
                i++; continue;
            }

            flushList();
            out.push(line);
            i++;
        }
        flushList();

        // --- Phase 5: inline formatting ---
        let html = out.join('\n');
        html = html.replace(/\*\*\*([^*\n]+)\*\*\*/g, '<strong><em>$1</em></strong>');
        html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
        html = html.replace(/~~([^~\n]+)~~/g, '<del>$1</del>');
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

        // Double newlines → paragraph breaks; single newlines → <br>
        html = html.replace(/\n\n+/g, '</p><p>');
        html = html.replace(/\n/g, '<br>');
        if (!html.startsWith('<')) html = `<p>${html}</p>`;

        // --- Phase 6: restore inline code ---
        inlineCodes.forEach((code, idx) => {
            html = html.split(`\x02INLINE${idx}\x03`).join(`<code>${code}</code>`);
        });

        // --- Phase 7: restore fenced code blocks ---
        codeBlocks.forEach(({ lang, code }, idx) => {
            const esc = Utils.escapeHtml(code.replace(/\n$/, ''));
            html = html.split(`\x02CODE${idx}\x03`).join(
                `<pre><code class="language-${lang}">${esc}</code></pre>`
            );
        });

        return html;
    },

    /**
     * Format timestamp for display
     */
    formatTime(timestamp) {
        const date = new Date(timestamp);
        return date.toLocaleTimeString('es-ES', {
            hour: '2-digit',
            minute: '2-digit'
        });
    },

    /**
     * Format relative time
     */
    formatRelativeTime(timestamp) {
        const now = new Date();
        const date = new Date(timestamp);
        const diff = Math.floor((now - date) / 1000);
        
        if (diff < 60) return 'ahora';
        if (diff < 3600) return `hace ${Math.floor(diff / 60)}m`;
        if (diff < 86400) return `hace ${Math.floor(diff / 3600)}h`;
        return date.toLocaleDateString('es-ES');
    },

    /**
     * Debounce function
     */
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },

    /**
     * Throttle function
     */
    throttle(func, limit) {
        let inThrottle;
        return function executedFunction(...args) {
            if (!inThrottle) {
                func(...args);
                inThrottle = true;
                setTimeout(() => inThrottle = false, limit);
            }
        };
    },

    /**
     * Local storage helpers
     */
    storage: {
        get(key, defaultValue = null) {
            try {
                const item = localStorage.getItem(key);
                return item ? JSON.parse(item) : defaultValue;
            } catch {
                return defaultValue;
            }
        },
        
        set(key, value) {
            try {
                localStorage.setItem(key, JSON.stringify(value));
            } catch (e) {
                console.error('Storage error:', e);
            }
        },
        
        remove(key) {
            localStorage.removeItem(key);
        }
    },

    /**
     * Show toast notification
     */
    showToast(message, type = 'info', duration = 3000) {
        const container = document.getElementById('toast-container');
        if (!container) return;
        
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        
        container.appendChild(toast);
        
        setTimeout(() => {
            toast.style.animation = 'slideIn 0.3s ease reverse';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    },

    /**
     * Copy text to clipboard
     */
    async copyToClipboard(text) {
        try {
            await navigator.clipboard.writeText(text);
            Utils.showToast('Copiado al portapapeles', 'success');
            return true;
        } catch {
            Utils.showToast('Error al copiar', 'error');
            return false;
        }
    },

    /**
     * Read file as text
     */
    readFileAsText(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsText(file);
        });
    },

    /**
     * Read file as base64
     */
    readFileAsBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => {
                const base64 = reader.result.split(',')[1];
                resolve(base64);
            };
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    },

    /**
     * Auto-resize textarea
     */
    autoResizeTextarea(textarea) {
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
    },

    /**
     * Scroll to bottom of element
     */
    scrollToBottom(element, smooth = true) {
        element.scrollTo({
            top: element.scrollHeight,
            behavior: smooth ? 'smooth' : 'auto'
        });
    },

    /**
     * Check if element is scrolled to bottom
     */
    isScrolledToBottom(element, threshold = 50) {
        return element.scrollHeight - element.scrollTop - element.clientHeight < threshold;
    },

    /**
     * Format file size
     */
    formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    },

    /**
     * Truncate path for display
     */
    truncatePath(path, maxLength = 30) {
        if (!path || path.length <= maxLength) return path;
        
        const parts = path.split('/');
        if (parts.length <= 2) return path;
        
        const first = parts[0] || '/';
        const last = parts[parts.length - 1];
        
        if (first.length + last.length + 5 > maxLength) {
            return '...' + path.slice(-maxLength + 3);
        }
        
        return first + '/.../' + last;
    }
};

// Make available globally
window.Utils = Utils;

// =============================================================================
// GFM Table helpers (used by Utils.parseMarkdown)
// Ported from Warp's crates/ai/src/gfm_table.rs
// =============================================================================

function _isGfmSeparator(line) {
    const trimmed = line.trim();
    if (!trimmed || !trimmed.includes('|')) return false;
    let hasCell = false;
    for (const cell of trimmed.split('|').map(c => c.trim())) {
        if (!cell) continue;
        const dashes = cell.replace(/^:/, '').replace(/:$/, '');
        if (!dashes || !/^-+$/.test(dashes)) return false;
        hasCell = true;
    }
    return hasCell;
}

function _parseTableRow(line) {
    return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
}

function _colAlign(cell) {
    const c = cell.trim();
    if (c.startsWith(':') && c.endsWith(':')) return 'center';
    if (c.endsWith(':')) return 'right';
    return 'left';
}

function _renderGfmTable(lines) {
    const headers = _parseTableRow(lines[0]);
    const aligns = _parseTableRow(lines[1]).map(_colAlign);
    const rows = lines.slice(2).map(_parseTableRow);

    let th = headers.map((h, i) =>
        `<th style="text-align:${aligns[i] || 'left'}">${h}</th>`
    ).join('');

    let tb = rows.map(row => {
        const tds = headers.map((_, i) =>
            `<td style="text-align:${aligns[i] || 'left'}">${row[i] ?? ''}</td>`
        ).join('');
        return `<tr>${tds}</tr>`;
    }).join('');

    return `<table><thead><tr>${th}</tr></thead><tbody>${tb}</tbody></table>`;
}
