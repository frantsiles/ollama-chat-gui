"""Vista de planes con edición y progreso."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

import streamlit as st

from core.models import Plan, PlanStatus, StepStatus


def render_plan_view(
    plan: Plan,
    on_approve: Optional[Callable[[], None]] = None,
    on_cancel: Optional[Callable[[], None]] = None,
    on_execute: Optional[Callable[[], None]] = None,
) -> None:
    """
    Renderiza la vista de un plan.
    
    Args:
        plan: Plan a renderizar
        on_approve: Callback para aprobar
        on_cancel: Callback para cancelar
        on_execute: Callback para ejecutar
    """
    # Header
    st.markdown(f"## 📋 {plan.title or 'Plan de Ejecución'}")
    
    if plan.description:
        st.markdown(plan.description)
    
    # Status
    status_colors = {
        PlanStatus.DRAFT: "🟡",
        PlanStatus.APPROVED: "🟢",
        PlanStatus.IN_PROGRESS: "🔵",
        PlanStatus.COMPLETED: "✅",
        PlanStatus.FAILED: "❌",
        PlanStatus.CANCELLED: "⚫",
    }
    
    status_icon = status_colors.get(plan.status, "⚪")
    completed, total = plan.progress
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Progreso", f"{completed}/{total}")
    with col2:
        st.markdown(f"**Estado:** {status_icon} {plan.status.value}")
    
    st.divider()
    
    # Pasos
    st.markdown("### Pasos")
    
    for step in plan.steps:
        step_status_icons = {
            StepStatus.PENDING: "⬜",
            StepStatus.IN_PROGRESS: "🔄",
            StepStatus.COMPLETED: "✅",
            StepStatus.FAILED: "❌",
            StepStatus.SKIPPED: "⏭️",
            StepStatus.AWAITING_APPROVAL: "⏸️",
        }
        
        icon = step_status_icons.get(step.status, "⬜")
        approval_mark = " 🔒" if step.requires_approval else ""
        
        with st.container():
            st.markdown(f"{icon} **{step.id}.** {step.description}{approval_mark}")
            
            if step.tool:
                st.caption(f"Tool: `{step.tool}`")
            
            if step.error_message:
                st.error(f"Error: {step.error_message}")
            
            if step.result and step.result.output:
                with st.expander("Ver resultado"):
                    st.code(step.result.output[:500])
    
    st.divider()
    
    # Botones de acción
    if plan.status == PlanStatus.DRAFT:
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Aprobar plan", type="primary", use_container_width=True):
                if on_approve:
                    on_approve()
        with col2:
            if st.button("❌ Cancelar", use_container_width=True):
                if on_cancel:
                    on_cancel()
    
    elif plan.status == PlanStatus.APPROVED:
        if st.button("▶️ Ejecutar plan", type="primary", use_container_width=True):
            if on_execute:
                on_execute()
    
    elif plan.status == PlanStatus.IN_PROGRESS:
        st.info("⏳ Plan en ejecución...")
    
    elif plan.status == PlanStatus.COMPLETED:
        st.success("✅ Plan completado exitosamente")
    
    elif plan.status == PlanStatus.FAILED:
        st.error("❌ El plan falló")
        if st.button("🔄 Reintentar", use_container_width=True):
            if on_execute:
                on_execute()


def render_plan_markdown(plan: Plan) -> None:
    """Renderiza el plan como markdown."""
    st.markdown(plan.to_markdown())


def render_plan_progress_bar(plan: Plan) -> None:
    """Renderiza una barra de progreso del plan."""
    completed, total = plan.progress
    if total > 0:
        progress = completed / total
        st.progress(progress, text=f"Progreso: {completed}/{total} pasos")
