# voicebot-SDE2-teamm
AI Voice Co-Pilot - Team SDE 2

## Contributor: Karthik N M
**Workstream:** W4 — Agentic Workflow Engine (Week 1 / Days 1–7)  
**Email:** karthiknm8050@gmail.com

---

### Workstream W4 (Agentic Workflow) Deliverables
- **Days 1–2:** Schemas (`WorkflowPlan`, `WorkflowStep`, `ToolSpec`, `ApprovalRequest`, `WorkflowResult`) and 7-state lifecycle state machine.
- **Days 3–4:** Two harmless mock tools (`knowledge_search`, `send_notification`), one consequential mock tool (`update_student_record`), `ToolRegistry`, and `WorkflowExecutor` with approval gating.
- **Days 5–6:** 35 unit tests validating invalid plans (cycles, missing dependencies, duplicate IDs) and state transitions.
- **Day 7:** Demonstration script (`demo.py`) running harmless, approved, and rejected execution scenarios.

---

### Running Tests
```bash
cd projects/sde-2-voicebot
python -m pytest tests -v
```

### Running Live Demo
```bash
python projects/sde-2-voicebot/demo.py
```
