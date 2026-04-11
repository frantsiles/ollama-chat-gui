
/**
 * Plan module - plan visualization and control
 */

const Plan = {
    panelEl: null,
    contentEl: null,
    actionsEl: null,
    currentPlan: null,

    /**
     * Initialize plan module
     */
    init() {
        this.panelEl = document.getElementById('plan-panel');
        this.contentEl = document.getElementById('plan-content');
        this.actionsEl = document.getElementById('plan-actions');

        this.bindEvents();
        this.setupWebSocketHandlers();
    },

    /**
     * Bind DOM events
     */
    bindEvents() {
        if (!this.panelEl || !this.contentEl || !this.actionsEl) {
            return;
        }
        // Close button
        const closeBtn = document.getElementById('close-plan');
        const approveBtn = document.getElementById('approve-plan');
        const rejectBtn = document.getElementById('reject-plan');

        if (!closeBtn || !approveBtn || !rejectBtn) {
            return;
        }

        closeBtn.addEventListener('click', () => {
            this.hide();
        });
    },

    /**
     * Setup WebSocket handlers
     */
    setupWebSocketHandlers() {
        wsManager.on('plan_approved', (data) => {
            this.currentPlan = data.plan;
            this.renderPlan();
            this.updateActions('approved');
            Utils.showToast('Plan aprobado', 'success');
            // En este flujo, al aprobar se debe ejecutar de inmediato
            this.execute();
        });

        wsManager.on('plan_rejected', () => {
            this.hide();
            Utils.showToast('Plan rechazado', 'info');
        });

        wsManager.on('plan_step_complete', (data) => {
            if (data.plan) {
                this.currentPlan = data.plan;
                this.renderPlan();
            }

            if (data.status === 'completed') {
                Utils.showToast('Plan completado exitosamente', 'success');
                this.updateActions('completed');
            } else if (data.status === 'failed' || data.status === 'error') {
                Utils.showToast(data.content || 'Error ejecutando plan', 'error');
                this.updateActions('failed');
            } else if (data.status === 'awaiting_approval') {
                this.updateActions('approved');
            }
        });
    },

    /**
     * Show plan panel with plan data
     */
    showPlan(plan) {
        this.currentPlan = plan;
        if (!this.panelEl) return;
        this.renderPlan();
        this.updateActions('draft');
        this.panelEl.style.display = 'flex';
    },

    /**
     * Hide plan panel
     */
    hide() {
        if (this.panelEl) {
            this.panelEl.style.display = 'none';
        }
        this.currentPlan = null;
    },

    /**
     * Render plan content
     */
    renderPlan() {
        if (!this.currentPlan || !this.contentEl) return;

        const plan = this.currentPlan;
        
        let html = `
            <div class="plan-title">
                <h4>${Utils.escapeHtml(plan.title || 'Plan de Ejecución')}</h4>
            </div>
        `;

        if (plan.description) {
            html += `<p class="plan-description">${Utils.escapeHtml(plan.description)}</p>`;
        }

        html += '<div class="plan-steps">';

        if (plan.steps && plan.steps.length > 0) {
            plan.steps.forEach((step, index) => {
                const statusClass = this.getStepStatusClass(step.status);
                const statusIcon = this.getStepStatusIcon(step.status);

                html += `
                    <div class="plan-step ${statusClass}">
                        <div class="plan-step-number">${statusIcon}</div>
                        <div class="plan-step-content">
                            <div class="plan-step-description">
                                ${Utils.escapeHtml(step.description)}
                            </div>
                            ${step.tool ? `
                                <div class="plan-step-tool">
                                    🔧 ${Utils.escapeHtml(step.tool)}
                                </div>
                            ` : ''}
                            ${step.error_message ? `
                                <div class="plan-step-error">
                                    ⚠️ ${Utils.escapeHtml(step.error_message)}
                                </div>
                            ` : ''}
                        </div>
                    </div>
                `;
            });
        } else {
            html += '<p class="no-steps">No hay pasos definidos</p>';
        }

        html += '</div>';

        // Progress bar
        const progress = this.calculateProgress(plan.steps);
        html += `
            <div class="plan-progress">
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${progress}%"></div>
                </div>
                <span class="progress-text">${progress}% completado</span>
            </div>
        `;

        this.contentEl.innerHTML = html;
    },

    /**
     * Get step status CSS class
     */
    getStepStatusClass(status) {
        const classes = {
            pending: '',
            in_progress: 'in-progress',
            completed: 'completed',
            failed: 'failed',
            skipped: 'skipped',
            awaiting_approval: 'awaiting'
        };
        return classes[status] || '';
    },

    /**
     * Get step status icon
     */
    getStepStatusIcon(status) {
        const icons = {
            pending: '○',
            in_progress: '◐',
            completed: '✓',
            failed: '✗',
            skipped: '⏭',
            awaiting_approval: '⏸'
        };
        return icons[status] || '○';
    },

    /**
     * Calculate progress percentage
     */
    calculateProgress(steps) {
        if (!steps || steps.length === 0) return 0;
        
        const completed = steps.filter(s => 
            s.status === 'completed' || s.status === 'skipped'
        ).length;
        
        return Math.round((completed / steps.length) * 100);
    },

    /**
     * Update action buttons based on plan status
     */
    updateActions(status) {
        const approveBtn = document.getElementById('approve-plan');
        const rejectBtn = document.getElementById('reject-plan');
        if (!approveBtn || !rejectBtn) return;

        switch (status) {
            case 'draft':
                approveBtn.textContent = '✓ Aprobar';
                approveBtn.disabled = false;
                approveBtn.onclick = () => this.approve();
                rejectBtn.style.display = 'block';
                rejectBtn.textContent = '✗ Rechazar';
                rejectBtn.onclick = () => this.reject();
                break;

            case 'approved':
                approveBtn.textContent = '▶ Ejecutar';
                approveBtn.disabled = false;
                approveBtn.onclick = () => this.execute();
                rejectBtn.style.display = 'none';
                break;

            case 'in_progress':
                approveBtn.textContent = '⏳ Ejecutando...';
                approveBtn.disabled = true;
                rejectBtn.style.display = 'none';
                break;

            case 'completed':
                approveBtn.textContent = '✓ Completado';
                approveBtn.disabled = true;
                rejectBtn.textContent = 'Cerrar';
                rejectBtn.style.display = 'block';
                rejectBtn.onclick = () => this.hide();
                break;

            case 'failed':
                approveBtn.textContent = '↻ Reintentar';
                approveBtn.disabled = false;
                approveBtn.onclick = () => this.execute();
                rejectBtn.style.display = 'block';
                rejectBtn.textContent = '✗ Rechazar';
                rejectBtn.onclick = () => this.reject();
                break;
        }
    },

    /**
     * Approve the current plan
     */
    approve() {
        if (!this.currentPlan) return;
        wsManager.sendPlanAction('approve');
    },

    /**
     * Reject the current plan
     */
    reject() {
        if (!this.currentPlan) return;
        wsManager.sendPlanAction('reject');
    },

    /**
     * Execute the current plan
     */
    execute() {
        if (!this.currentPlan) return;
        this.updateActions('in_progress');
        wsManager.sendPlanAction('execute');
    }
};

// Add some additional CSS for plan module
const planStyles = document.createElement('style');
planStyles.textContent = `
    .plan-title h4 {
        margin: 0 0 var(--space-sm) 0;
        font-size: var(--text-lg);
    }

    .plan-description {
        color: var(--text-secondary);
        margin-bottom: var(--space-md);
        font-size: var(--text-sm);
    }

    .plan-steps {
        display: flex;
        flex-direction: column;
        gap: var(--space-sm);
        margin-bottom: var(--space-md);
    }

    .plan-step-error {
        color: var(--accent-danger);
        font-size: var(--text-xs);
        margin-top: var(--space-xs);
    }

    .plan-progress {
        display: flex;
        align-items: center;
        gap: var(--space-sm);
    }

    .progress-bar {
        flex: 1;
        height: 6px;
        background: var(--bg-tertiary);
        border-radius: var(--radius-full);
        overflow: hidden;
    }

    .progress-fill {
        height: 100%;
        background: var(--accent-primary);
        transition: width var(--transition-normal);
    }

    .progress-text {
        font-size: var(--text-xs);
        color: var(--text-secondary);
        min-width: 80px;
        text-align: right;
    }

    .no-steps {
        color: var(--text-tertiary);
        text-align: center;
        padding: var(--space-lg);
    }
`;
document.head.appendChild(planStyles);

// Make available globally
window.Plan = Plan;
