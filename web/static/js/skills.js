/**
 * Skills module — gestiona el sistema de skills inspirado en Warp's .agents/skills/
 * También controla los selectores del input (modo, skill, modelo).
 */

const Skills = {
    skills: [],
    activeSkill: null,   // nombre del skill activo, o null

    init() {
        this._bindTopRowSelectors();
        this._bindManageBtn();
        this._loadSkills();
    },

    // =========================================================================
    // Top-row selectors: mode, skill, model
    // =========================================================================

    _bindTopRowSelectors() {
        // --- Mode selector ---
        const modeBtn  = document.getElementById('mode-selector-btn');
        const modeMenu = document.getElementById('mode-selector-menu');
        if (modeBtn && modeMenu) {
            modeBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this._toggleMenu(modeBtn, modeMenu);
            });
            modeMenu.querySelectorAll('.selector-menu-item').forEach(item => {
                item.addEventListener('click', () => {
                    const mode = item.dataset.mode;
                    this._setMode(mode);
                    this._closeMenu(modeBtn, modeMenu);
                });
            });
        }

        // --- Skill selector ---
        const skillBtn  = document.getElementById('skill-selector-btn');
        const skillMenu = document.getElementById('skill-selector-menu');
        if (skillBtn && skillMenu) {
            skillBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this._toggleMenu(skillBtn, skillMenu);
            });
        }

        // --- Model picker ---
        const modelBtn  = document.getElementById('model-picker-btn');
        const modelMenu = document.getElementById('model-picker-menu');
        if (modelBtn && modelMenu) {
            modelBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this._toggleMenu(modelBtn, modelMenu);
            });
        }

        // Close all menus on outside click
        document.addEventListener('click', () => this._closeAllMenus());
    },

    _toggleMenu(btn, menu) {
        const isOpen = menu.classList.contains('open');
        this._closeAllMenus();
        if (!isOpen) {
            menu.classList.add('open');
            btn.setAttribute('aria-expanded', 'true');
        }
    },

    _closeMenu(btn, menu) {
        menu.classList.remove('open');
        if (btn) btn.setAttribute('aria-expanded', 'false');
    },

    _closeAllMenus() {
        document.querySelectorAll('.input-selector-menu.open').forEach(m => {
            m.classList.remove('open');
        });
        document.querySelectorAll('[aria-expanded="true"]').forEach(b => {
            b.setAttribute('aria-expanded', 'false');
        });
    },

    // =========================================================================
    // Mode selector
    // =========================================================================

    _setMode(mode) {
        // Delegate to Modes module if available
        if (window.Modes && typeof Modes.setMode === 'function') {
            Modes.setMode(mode);
        } else if (window.Sidebar && typeof Sidebar.updateServerConfig === 'function') {
            Sidebar.updateServerConfig(mode);
        }
        this.updateModeLabel(mode);
    },

    updateModeLabel(mode) {
        const label = document.getElementById('mode-selector-label');
        if (!label) return;
        const names = { agent: 'Agent', chat: 'Chat', plan: 'Plan' };
        label.textContent = names[mode] || mode;

        // Update active state in menu
        document.querySelectorAll('#mode-selector-menu .selector-menu-item').forEach(item => {
            item.classList.toggle('active', item.dataset.mode === mode);
        });
    },

    // =========================================================================
    // Model picker
    // =========================================================================

    populateModelMenu(models) {
        const menu  = document.getElementById('model-picker-menu');
        const label = document.getElementById('model-picker-label');
        if (!menu) return;

        // Get currently selected model
        const sidebarSelect = document.getElementById('model-select');
        const current = sidebarSelect ? sidebarSelect.value : '';

        menu.innerHTML = '';
        if (!models || models.length === 0) {
            menu.innerHTML = '<div class="selector-menu-empty">No hay modelos disponibles</div>';
            return;
        }

        models.forEach(m => {
            const name = typeof m === 'string' ? m : m.name;
            const caps = (typeof m === 'object' && m.capabilities) ? m.capabilities : [];
            const item = document.createElement('button');
            item.className = 'selector-menu-item' + (name === current ? ' active' : '');
            item.dataset.model = name;
            item.role = 'menuitem';

            const capBadges = [
                caps.includes('tools')  ? '<span class="model-cap-dot tools-dot" title="Tool calling nativo">⚡</span>' : '',
                caps.includes('vision') ? '<span class="model-cap-dot vision-dot" title="Soporta imágenes">👁</span>' : '',
            ].join('');

            item.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" stroke-width="2">
                <ellipse cx="12" cy="5" rx="9" ry="3"/>
                <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/>
                <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
            </svg><span class="model-menu-name">${this._shortModelName(name)}</span>${capBadges}`;

            item.addEventListener('click', () => {
                this._selectModel(name);
                this._closeAllMenus();
            });
            menu.appendChild(item);
        });

        if (current && label) label.textContent = this._shortModelName(current);
    },

    _selectModel(name) {
        // Sync with sidebar select
        const sidebarSelect = document.getElementById('model-select');
        if (sidebarSelect) {
            sidebarSelect.value = name;
            sidebarSelect.dispatchEvent(new Event('change'));
        }
        // Update label
        const label = document.getElementById('model-picker-label');
        if (label) label.textContent = this._shortModelName(name);
        // Update active state
        document.querySelectorAll('#model-picker-menu .selector-menu-item').forEach(item => {
            item.classList.toggle('active', item.dataset.model === name);
        });
    },

    updateModelLabel(name) {
        const label = document.getElementById('model-picker-label');
        if (label) label.textContent = this._shortModelName(name || '-');
        // Sync active state in menu
        document.querySelectorAll('#model-picker-menu .selector-menu-item').forEach(item => {
            item.classList.toggle('active', item.dataset.model === name);
        });
    },

    _shortModelName(name) {
        // "llama3.2:3b" → "llama3.2:3b" (keep as is, just truncate if very long)
        return name && name.length > 26 ? name.slice(0, 24) + '…' : (name || '-');
    },

    // =========================================================================
    // Skills API
    // =========================================================================

    async _loadSkills() {
        try {
            const res = await fetch('/api/skills');
            if (!res.ok) return;
            const data = await res.json();
            this.skills = data.skills || [];
            this._renderSkillMenu();
        } catch (_) { /* silently ignore if API not ready */ }
    },

    async _createSkill(name, description, content) {
        const res = await fetch('/api/skills', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, description, content }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Error creando skill');
        }
        const data = await res.json();
        this.skills.push(data.skill);
        this._renderSkillMenu();
        return data.skill;
    },

    async _updateSkill(name, description, content) {
        const res = await fetch(`/api/skills/${encodeURIComponent(name)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ description, content }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.detail || 'Error actualizando skill');
        }
        const data = await res.json();
        const idx = this.skills.findIndex(s => s.name === name);
        if (idx !== -1) this.skills[idx] = data.skill;
        this._renderSkillMenu();
        return data.skill;
    },

    async _deleteSkill(name) {
        const res = await fetch(`/api/skills/${encodeURIComponent(name)}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Error eliminando skill');
        this.skills = this.skills.filter(s => s.name !== name);
        if (this.activeSkill === name) this.setActiveSkill(null);
        this._renderSkillMenu();
    },

    // =========================================================================
    // Skill selector menu
    // =========================================================================

    _renderSkillMenu() {
        const itemsEl  = document.getElementById('skill-menu-items');
        const emptyEl  = document.getElementById('skill-menu-empty');
        if (!itemsEl) return;

        itemsEl.innerHTML = '';

        if (this.skills.length === 0) {
            if (emptyEl) emptyEl.style.display = '';
            return;
        }
        if (emptyEl) emptyEl.style.display = 'none';

        // "None" option
        const noneItem = document.createElement('button');
        noneItem.className = 'selector-menu-item' + (!this.activeSkill ? ' active' : '');
        noneItem.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
        </svg>Sin skill`;
        noneItem.addEventListener('click', () => {
            this.setActiveSkill(null);
            this._closeAllMenus();
        });
        itemsEl.appendChild(noneItem);

        this.skills.forEach(skill => {
            const item = document.createElement('button');
            item.className = 'selector-menu-item' + (this.activeSkill === skill.name ? ' active' : '');
            item.title = skill.description || '';
            item.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" stroke-width="2">
                <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
            </svg>${Utils.escapeHtml(skill.name)}`;
            item.addEventListener('click', () => {
                this.setActiveSkill(skill.name);
                this._closeAllMenus();
            });
            itemsEl.appendChild(item);
        });
    },

    setActiveSkill(name) {
        this.activeSkill = name || null;

        // Update label
        const label = document.getElementById('skill-selector-label');
        if (label) label.textContent = name || 'Sin skill';

        // Notify server
        if (wsManager.sessionId) {
            fetch(`/api/sessions/${wsManager.sessionId}/config`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ active_skill: name || '' }),
            }).catch(() => {});
        }

        // Update active state in menu
        document.querySelectorAll('#skill-menu-items .selector-menu-item').forEach(item => {
            item.classList.toggle('active',
                name ? item.textContent.trim().endsWith(name) : item.textContent.includes('Sin skill')
            );
        });

        if (name) {
            Utils.showToast(`Skill activo: ${name}`, 'success', 2000);
        }
    },

    // =========================================================================
    // Skills management modal
    // =========================================================================

    _bindManageBtn() {
        const btn = document.getElementById('manage-skills-btn');
        if (btn) btn.addEventListener('click', () => this.openManageModal());
    },

    openManageModal() {
        // Remove any existing modal
        document.getElementById('skills-modal')?.remove();

        const modal = document.createElement('div');
        modal.id = 'skills-modal';
        modal.className = 'skills-modal-overlay';
        modal.innerHTML = `
            <div class="skills-modal" role="dialog" aria-modal="true" aria-label="Gestionar Skills">
                <div class="skills-modal-header">
                    <h3>Skills</h3>
                    <button class="skills-modal-close" id="skills-modal-close" aria-label="Cerrar">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                            <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                    </button>
                </div>
                <div class="skills-modal-body">
                    <div class="skills-list" id="skills-list"></div>
                    <div class="skills-form-section">
                        <h4 id="skills-form-title">Nuevo skill</h4>
                        <div class="skills-form" id="skills-form">
                            <input type="text" id="skill-form-name" class="skills-input"
                                placeholder="nombre-del-skill (sin espacios)" autocomplete="off"/>
                            <input type="text" id="skill-form-desc" class="skills-input"
                                placeholder="Descripción breve…" autocomplete="off"/>
                            <textarea id="skill-form-content" class="skills-textarea"
                                placeholder="Instrucciones para el modelo…\n\nEj: Responde siempre en inglés técnico, incluye ejemplos de código, prioriza la claridad sobre la brevedad." rows="6"></textarea>
                            <div class="skills-form-actions">
                                <button id="skill-form-cancel" class="btn btn-ghost" style="display:none">Cancelar</button>
                                <button id="skill-form-save" class="btn btn-primary">Crear skill</button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

        // Close on backdrop click
        modal.addEventListener('click', (e) => {
            if (e.target === modal) this.closeManageModal();
        });
        document.getElementById('skills-modal-close')
            .addEventListener('click', () => this.closeManageModal());

        // Escape key
        this._modalKeyHandler = (e) => {
            if (e.key === 'Escape') this.closeManageModal();
        };
        document.addEventListener('keydown', this._modalKeyHandler);

        this._renderModalList();
        this._bindModalForm();
    },

    closeManageModal() {
        document.getElementById('skills-modal')?.remove();
        if (this._modalKeyHandler) {
            document.removeEventListener('keydown', this._modalKeyHandler);
            this._modalKeyHandler = null;
        }
    },

    _renderModalList() {
        const listEl = document.getElementById('skills-list');
        if (!listEl) return;

        if (this.skills.length === 0) {
            listEl.innerHTML = `<p class="skills-empty">No hay skills. Crea el primero →</p>`;
            return;
        }

        listEl.innerHTML = this.skills.map(skill => `
            <div class="skill-item" data-name="${Utils.escapeHtml(skill.name)}">
                <div class="skill-item-info">
                    <span class="skill-item-name">${Utils.escapeHtml(skill.name)}</span>
                    <span class="skill-item-desc">${Utils.escapeHtml(skill.description || '')}</span>
                </div>
                <div class="skill-item-actions">
                    <button class="skill-action-btn skill-edit-btn" data-name="${Utils.escapeHtml(skill.name)}" title="Editar">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                        </svg>
                    </button>
                    <button class="skill-action-btn skill-delete-btn" data-name="${Utils.escapeHtml(skill.name)}" title="Eliminar">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"/>
                            <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>
                            <path d="M10 11v6M14 11v6"/>
                            <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>
                        </svg>
                    </button>
                </div>
            </div>
        `).join('');

        listEl.querySelectorAll('.skill-edit-btn').forEach(btn => {
            btn.addEventListener('click', () => this._editSkill(btn.dataset.name));
        });
        listEl.querySelectorAll('.skill-delete-btn').forEach(btn => {
            btn.addEventListener('click', () => this._confirmDeleteSkill(btn.dataset.name));
        });
    },

    _bindModalForm() {
        const saveBtn   = document.getElementById('skill-form-save');
        const cancelBtn = document.getElementById('skill-form-cancel');
        if (!saveBtn) return;

        saveBtn.addEventListener('click', async () => {
            const name    = document.getElementById('skill-form-name').value.trim();
            const desc    = document.getElementById('skill-form-desc').value.trim();
            const content = document.getElementById('skill-form-content').value.trim();

            if (!name) { Utils.showToast('El nombre es requerido', 'error'); return; }
            if (!content) { Utils.showToast('Las instrucciones son requeridas', 'error'); return; }
            if (!/^[\w-]+$/.test(name)) {
                Utils.showToast('El nombre solo puede contener letras, números, guiones y guiones bajos', 'error');
                return;
            }

            try {
                saveBtn.disabled = true;
                if (saveBtn.dataset.editing) {
                    await this._updateSkill(saveBtn.dataset.editing, desc, content);
                    Utils.showToast(`Skill "${name}" actualizado`, 'success');
                } else {
                    await this._createSkill(name, desc, content);
                    Utils.showToast(`Skill "${name}" creado`, 'success');
                }
                this._resetForm();
                this._renderModalList();
            } catch (err) {
                Utils.showToast(err.message, 'error');
            } finally {
                saveBtn.disabled = false;
            }
        });

        cancelBtn?.addEventListener('click', () => this._resetForm());
    },

    _editSkill(name) {
        const skill = this.skills.find(s => s.name === name);
        if (!skill) return;

        // Extract content without frontmatter for display
        const contentBody = skill.content
            .replace(/\A?\s*---[\s\S]*?---\s*\n/, '')
            .trim();

        document.getElementById('skill-form-name').value = skill.name;
        document.getElementById('skill-form-name').disabled = true;
        document.getElementById('skill-form-desc').value = skill.description || '';
        document.getElementById('skill-form-content').value = contentBody;

        const saveBtn = document.getElementById('skill-form-save');
        const cancelBtn = document.getElementById('skill-form-cancel');
        const title = document.getElementById('skills-form-title');

        if (saveBtn) { saveBtn.textContent = 'Guardar cambios'; saveBtn.dataset.editing = name; }
        if (cancelBtn) cancelBtn.style.display = '';
        if (title) title.textContent = `Editando: ${name}`;
    },

    _resetForm() {
        const nameInput = document.getElementById('skill-form-name');
        if (nameInput) { nameInput.value = ''; nameInput.disabled = false; }
        const descInput = document.getElementById('skill-form-desc');
        if (descInput) descInput.value = '';
        const contentInput = document.getElementById('skill-form-content');
        if (contentInput) contentInput.value = '';

        const saveBtn = document.getElementById('skill-form-save');
        if (saveBtn) { saveBtn.textContent = 'Crear skill'; delete saveBtn.dataset.editing; }
        const cancelBtn = document.getElementById('skill-form-cancel');
        if (cancelBtn) cancelBtn.style.display = 'none';
        const title = document.getElementById('skills-form-title');
        if (title) title.textContent = 'Nuevo skill';
    },

    async _confirmDeleteSkill(name) {
        if (!confirm(`¿Eliminar el skill "${name}"?`)) return;
        try {
            await this._deleteSkill(name);
            Utils.showToast(`Skill "${name}" eliminado`, 'success');
            this._renderModalList();
        } catch (err) {
            Utils.showToast(err.message, 'error');
        }
    },
};

window.Skills = Skills;
