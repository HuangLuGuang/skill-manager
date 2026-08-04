"""
agent-manager CLI

Commands:
  submit      Vet and submit a skill
  review      Human review queue (list / approve / reject)
  registry    Inspect the skill registry (list / show)
  deploy      Mark an approved skill as deployed
  retire      Revoke a skill from all agents
  audit       Show the audit trail
  runtime     Runtime guard tools (check / verify)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv()

import click
from rich.console import Console
from rich.table import Table
from rich import box
from rich.panel import Panel
from rich.text import Text

from agent_manager.core.prompt_models import PromptStatus

console = Console()
err_console = Console(stderr=True)


def _load_manager(policy_path: str | None):
    from agent_manager.core.manager import AgentManager
    from agent_manager.core.policy import CompanyPolicy

    if policy_path:
        policy = CompanyPolicy.load(policy_path)
    else:
        # Auto-discover company-policy.yaml in cwd or ~/.agent-manager/
        for candidate in ["company-policy.yaml", Path.home() / ".agent-manager" / "policy.yaml"]:
            if Path(candidate).exists():
                policy = CompanyPolicy.load(candidate)
                break
        else:
            policy = CompanyPolicy.default()

    return AgentManager(policy=policy)


def _risk_color(risk: str) -> str:
    return {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red", "EXTREME": "bold red"}.get(risk, "white")


def _status_color(status: str) -> str:
    return {
        "PENDING": "dim",
        "VETTED": "yellow",
        "APPROVED": "green",
        "DEPLOYED": "bold green",
        "REJECTED": "red",
        "RETIRED": "dim red",
    }.get(status, "white")


# --------------------------------------------------------------------------- #
# Root group                                                                    #
# --------------------------------------------------------------------------- #

@click.group()
@click.option("--policy", "policy_path", default=None, metavar="PATH",
              help="Path to company-policy.yaml (auto-discovered if omitted)")
@click.pass_context
def main(ctx: click.Context, policy_path: str | None):
    """Enterprise skill lifecycle manager for AI agents."""
    ctx.ensure_object(dict)
    ctx.obj["policy_path"] = policy_path


# --------------------------------------------------------------------------- #
# signing-key                                                                   #
# --------------------------------------------------------------------------- #

@main.group("signing-key")
def signing_key():
    """Manage the server Ed25519 signing identity."""


@signing_key.command("init")
def signing_key_init():
    """Create the signing key if it does not already exist."""
    from agent_manager.core.signer import ensure_signing_key, signing_key_id

    path = ensure_signing_key()
    click.echo(json.dumps({
        "path": str(path),
        "key_id": signing_key_id(),
        "created_or_existing": True,
    }, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# submit                                                                        #
# --------------------------------------------------------------------------- #

@main.command()
@click.argument("skill_path", type=click.Path(exists=True, file_okay=False))
@click.option("--author", default=None, help="Skill author/publisher identifier")
@click.option("--origin", default="local",
              type=click.Choice(["local", "github", "clawhub", "internal"]),
              help="Where the skill came from")
@click.option("--behavioral", is_flag=True, default=False,
              help="Enable rule-based analysis (slower, more thorough)")
@click.option("--llm", is_flag=True, default=False,
              help="Enable LLM semantic analysis (requires API key)")
@click.option("--sandbox", is_flag=True, default=False,
              help="Enable Docker sandbox execution probe (requires Docker)")
@click.option("--json", "output_json", is_flag=True, default=False,
              help="Output result as JSON")
@click.pass_context
def submit(ctx, skill_path, author, origin, behavioral, llm, sandbox, output_json):
    """Vet and submit a skill to the registry."""
    from agent_manager.core.models import SourceInfo, SkillOrigin

    mgr = _load_manager(ctx.obj["policy_path"])

    source = SourceInfo(
        origin=SkillOrigin(origin),
        author=author,
    )

    with console.status(f"[bold]Vetting skill at {skill_path}...[/bold]"):
        try:
            entry = mgr.submit(
                skill_path,
                source=source,
                use_behavioral=behavioral,
                use_llm=llm,
                use_sandbox=sandbox,
            )
        except Exception as e:
            err_console.print(f"[red]Error:[/red] {e}")
            sys.exit(1)

    if output_json:
        click.echo(json.dumps(entry.model_dump(mode="json"), indent=2, default=str))
        return

    status_col = _status_color(entry.status.value)
    risk_col = _risk_color(entry.risk_level.value if entry.risk_level else "LOW")

    console.print()
    console.print(Panel.fit(
        f"[bold]{entry.name}[/bold]  [dim]{entry.skill_id[:8]}[/dim]",
        title="Skill Submitted",
    ))

    rows = [
        ("Status", f"[{status_col}]{entry.status.value}[/{status_col}]"),
        ("Risk", f"[{risk_col}]{entry.risk_level.value if entry.risk_level else '—'}[/{risk_col}]"),
        ("Findings", str(entry.vetting.findings_count if entry.vetting else 0)),
        ("Allowed tools", ", ".join(entry.allowed_tools) if entry.allowed_tools else "[dim]none declared[/dim]"),
    ]
    if entry.vetting and entry.vetting.policy_notes:
        rows.append(("Policy notes", "\n".join(entry.vetting.policy_notes)))

    for label, value in rows:
        console.print(f"  [bold]{label}:[/bold] {value}")

    console.print()
    if entry.status.value == "APPROVED":
        console.print("[green]Auto-approved.[/green] Run [bold]agent-manager deploy[/bold] to activate.")
    elif entry.status.value == "VETTED":
        console.print("[yellow]Queued for human review.[/yellow] Run [bold]agent-manager review list[/bold].")
    elif entry.status.value == "REJECTED":
        console.print("[red]Rejected by policy.[/red]")
        if entry.rejection_reason:
            console.print(f"  Reason: {entry.rejection_reason}")


# --------------------------------------------------------------------------- #
# review                                                                        #
# --------------------------------------------------------------------------- #

@main.group()
def review():
    """Human review queue for HIGH/EXTREME risk skills."""


@review.command("list")
@click.pass_context
def review_list(ctx):
    """List skills pending human review."""
    mgr = _load_manager(ctx.obj["policy_path"])
    queue = mgr.list_review_queue()

    if not queue:
        console.print("[dim]Review queue is empty.[/dim]")
        return

    t = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold")
    t.add_column("ID (short)", style="dim")
    t.add_column("Skill Name")
    t.add_column("Risk")
    t.add_column("Findings (C/H/M/L)")
    t.add_column("Queued At")

    for r in queue:
        risk_col = _risk_color(r.risk_level.value)
        fs = r.findings_summary
        t.add_row(
            r.skill_id[:8],
            r.skill_name,
            f"[{risk_col}]{r.risk_level.value}[/{risk_col}]",
            f"{fs.get('critical',0)}/{fs.get('high',0)}/{fs.get('medium',0)}/{fs.get('low',0)}",
            r.queued_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(t)
    console.print(f"[dim]{len(queue)} skill(s) awaiting review.[/dim]")


@review.command("approve")
@click.argument("skill_id")
@click.option("--approver", required=True, help="Your name/username")
@click.option("--note", default=None, help="Optional approval note")
@click.pass_context
def review_approve(ctx, skill_id, approver, note):
    """Approve a vetted skill."""
    mgr = _load_manager(ctx.obj["policy_path"])

    # Allow short ID prefix
    entry = _resolve_skill(mgr, skill_id)

    try:
        entry = mgr.approve(entry.skill_id, approver=approver, note=note)
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    console.print(f"[green]Approved[/green] skill [bold]{entry.name!r}[/bold] "
                  f"(signed, ready to deploy)")


@review.command("reject")
@click.argument("skill_id")
@click.option("--reviewer", required=True, help="Your name/username")
@click.option("--reason", required=True, help="Rejection reason")
@click.pass_context
def review_reject(ctx, skill_id, reviewer, reason):
    """Reject a vetted skill."""
    mgr = _load_manager(ctx.obj["policy_path"])
    entry = _resolve_skill(mgr, skill_id)

    try:
        entry = mgr.reject(entry.skill_id, reviewer=reviewer, reason=reason)
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    console.print(f"[red]Rejected[/red] skill [bold]{entry.name!r}[/bold]")


# --------------------------------------------------------------------------- #
# registry                                                                      #
# --------------------------------------------------------------------------- #

@main.group()
def registry():
    """Inspect the skill registry."""


@registry.command("list")
@click.option("--status", default=None,
              type=click.Choice(["PENDING","VETTED","APPROVED","DEPLOYED","REJECTED","RETIRED"]),
              help="Filter by status")
@click.option("--json", "output_json", is_flag=True, default=False)
@click.pass_context
def registry_list(ctx, status, output_json):
    """List all skills in the registry."""
    from agent_manager.core.models import SkillStatus

    mgr = _load_manager(ctx.obj["policy_path"])
    entries = mgr.list_skills(SkillStatus(status) if status else None)

    if output_json:
        click.echo(json.dumps([e.model_dump(mode="json") for e in entries], indent=2, default=str))
        return

    if not entries:
        console.print("[dim]Registry is empty.[/dim]")
        return

    t = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold")
    t.add_column("ID (short)", style="dim")
    t.add_column("Name")
    t.add_column("Status")
    t.add_column("Risk")
    t.add_column("Approved By")
    t.add_column("Submitted")

    for e in entries:
        sc = _status_color(e.status.value)
        rc = _risk_color(e.risk_level.value if e.risk_level else "LOW")
        t.add_row(
            e.skill_id[:8],
            e.name,
            f"[{sc}]{e.status.value}[/{sc}]",
            f"[{rc}]{e.risk_level.value if e.risk_level else '—'}[/{rc}]",
            e.approved_by or "—",
            e.submitted_at.strftime("%Y-%m-%d"),
        )

    console.print(t)


@registry.command("show")
@click.argument("skill_id_or_name")
@click.option("--json", "output_json", is_flag=True, default=False)
@click.pass_context
def registry_show(ctx, skill_id_or_name, output_json):
    """Show detailed information for a skill."""
    mgr = _load_manager(ctx.obj["policy_path"])
    entry = mgr.get_skill(skill_id_or_name)

    if entry is None:
        err_console.print(f"[red]Skill {skill_id_or_name!r} not found.[/red]")
        sys.exit(1)

    if output_json:
        click.echo(json.dumps(entry.model_dump(mode="json"), indent=2, default=str))
        return

    sc = _status_color(entry.status.value)
    rc = _risk_color(entry.risk_level.value if entry.risk_level else "LOW")

    console.print(Panel.fit(f"[bold]{entry.name}[/bold]  [dim]{entry.skill_id}[/dim]"))
    console.print(f"  [bold]Description:[/bold] {entry.description}")
    console.print(f"  [bold]Status:[/bold] [{sc}]{entry.status.value}[/{sc}]")
    console.print(f"  [bold]Risk:[/bold] [{rc}]{entry.risk_level.value if entry.risk_level else '—'}[/{rc}]")
    console.print(f"  [bold]Source:[/bold] {entry.source.origin.value}"
                  + (f" / {entry.source.author}" if entry.source.author else ""))
    console.print(f"  [bold]Path:[/bold] {entry.skill_path or '—'}")
    console.print(f"  [bold]Allowed tools:[/bold] {', '.join(entry.allowed_tools) or '[dim]none[/dim]'}")
    console.print(f"  [bold]Signature:[/bold] {entry.signature[:16] + '...' if entry.signature else '[dim]unsigned[/dim]'}")
    console.print(f"  [bold]Submitted:[/bold] {entry.submitted_at.isoformat()}")
    if entry.approved_at:
        console.print(f"  [bold]Approved:[/bold] {entry.approved_at.isoformat()} by {entry.approved_by}")
    if entry.deployed_at:
        console.print(f"  [bold]Deployed:[/bold] {entry.deployed_at.isoformat()}")
    if entry.retired_at:
        console.print(f"  [bold]Retired:[/bold] {entry.retired_at.isoformat()} — {entry.retire_reason}")

    if entry.vetting:
        v = entry.vetting
        console.print()
        console.print(f"  [bold]Scan:[/bold] {v.findings_count} findings "
                      f"risk={v.risk_level.value} "
                      f"in {v.scan_duration_seconds:.1f}s")
        if v.policy_notes:
            for note in v.policy_notes:
                console.print(f"    [yellow]{note}[/yellow]")


@registry.command("audit-tool-permissions")
@click.option("--json", "output_json", is_flag=True, default=False)
@click.pass_context
def registry_audit_tool_permissions(ctx, output_json):
    """Find loadable skills that declare no allowed_tools."""
    mgr = _load_manager(ctx.obj["policy_path"])
    affected = [
        entry
        for entry in mgr.list_skills()
        if entry.is_loadable() and not entry.allowed_tools
    ]
    payload = [
        {
            "skill_id": entry.skill_id,
            "name": entry.name,
            "status": entry.status.value,
            "version_no": entry.version_no,
        }
        for entry in affected
    ]
    if output_json:
        click.echo(json.dumps(payload, indent=2, ensure_ascii=False))
    elif affected:
        table = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold")
        table.add_column("ID (short)", style="dim")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("Version")
        for entry in affected:
            table.add_row(
                entry.skill_id[:8],
                entry.name,
                entry.status.value,
                str(entry.version_no or "—"),
            )
        console.print(table)
        err_console.print(
            "[red]These loadable skills declare no allowed_tools and will be blocked "
            "by fail-closed runtime authorization.[/red]"
        )
    else:
        console.print("[green]No loadable skills with empty allowed_tools.[/green]")

    if affected:
        ctx.exit(2)


# --------------------------------------------------------------------------- #
# deploy                                                                        #
# --------------------------------------------------------------------------- #

@main.command()
@click.argument("skill_id_or_name")
@click.option("--actor", default=None, help="Who is deploying this skill")
@click.pass_context
def deploy(ctx, skill_id_or_name, actor):
    """Mark an approved skill as deployed (active in production)."""
    mgr = _load_manager(ctx.obj["policy_path"])
    entry = _resolve_skill(mgr, skill_id_or_name)

    try:
        entry = mgr.deploy(entry.skill_id, actor=actor)
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    console.print(f"[bold green]Deployed[/bold green] skill [bold]{entry.name!r}[/bold]")


# --------------------------------------------------------------------------- #
# retire                                                                        #
# --------------------------------------------------------------------------- #

@main.command()
@click.argument("skill_id_or_name")
@click.option("--reason", required=True, help="Why this skill is being retired")
@click.option("--actor", default=None, help="Who is retiring this skill")
@click.pass_context
def retire(ctx, skill_id_or_name, reason, actor):
    """Retire a skill — immediately revokes loadability from all agents."""
    mgr = _load_manager(ctx.obj["policy_path"])

    try:
        entry = mgr.retire(skill_id_or_name, reason=reason, actor=actor)
    except Exception as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    console.print(f"[bold red]Retired[/bold red] skill [bold]{entry.name!r}[/bold] — {reason}")


# --------------------------------------------------------------------------- #
# audit                                                                         #
# --------------------------------------------------------------------------- #

@main.command()
@click.option("--since", default=None, metavar="HOURS",
              help="Show events from last N hours (default: 24)")
@click.option("--skill", default=None, metavar="SKILL_ID",
              help="Filter by skill ID")
@click.option("--limit", default=50, show_default=True, help="Max events to show")
@click.option("--json", "output_json", is_flag=True, default=False)
@click.pass_context
def audit(ctx, since, skill, limit, output_json):
    """Show the audit trail."""
    mgr = _load_manager(ctx.obj["policy_path"])

    since_dt = None
    if since is not None:
        since_dt = datetime.now(timezone.utc) - timedelta(hours=float(since))
    elif since is None:
        since_dt = datetime.now(timezone.utc) - timedelta(hours=24)

    events = mgr.audit(since=since_dt, skill_id=skill, limit=limit)

    if output_json:
        click.echo(json.dumps(
            [e.model_dump(mode="json") for e in events], indent=2, default=str
        ))
        return

    if not events:
        console.print("[dim]No audit events found.[/dim]")
        return

    t = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold")
    t.add_column("Time")
    t.add_column("Event")
    t.add_column("Skill")
    t.add_column("Actor")
    t.add_column("Details")

    _event_color = {
        "skill_approved": "green",
        "skill_deployed": "bold green",
        "skill_rejected": "red",
        "skill_retired": "bold red",
        "skill_load_blocked": "red",
        "skill_tamper_detected": "bold red",
        "tool_blocked": "yellow",
    }

    for e in events:
        col = _event_color.get(e.event_type, "white")
        details_str = ", ".join(f"{k}={v}" for k, v in list(e.details.items())[:3])
        t.add_row(
            e.timestamp.strftime("%m-%d %H:%M"),
            f"[{col}]{e.event_type}[/{col}]",
            e.skill_name,
            e.actor or "—",
            details_str,
        )

    console.print(t)


# --------------------------------------------------------------------------- #
# runtime                                                                       #
# --------------------------------------------------------------------------- #

@main.group()
def runtime():
    """Runtime guard utilities."""


@runtime.command("check")
@click.argument("skill_name")
@click.option("--path", "skill_path", default=None,
              help="Skill path for signature verification")
@click.option("--agent", default=None, help="Agent ID making the request")
@click.pass_context
def runtime_check(ctx, skill_name, skill_path, agent):
    """Check whether a skill can be loaded by an agent."""
    mgr = _load_manager(ctx.obj["policy_path"])

    allowed, entry, reason = mgr.runtime.can_load(
        skill_name, skill_path=skill_path, agent_id=agent
    )

    if allowed:
        console.print(f"[green]ALLOWED[/green] — {skill_name!r} can be loaded")
        if entry:
            console.print(f"  Status: {entry.status.value}  Risk: {entry.risk_level.value if entry.risk_level else '—'}")
    else:
        console.print(f"[red]BLOCKED[/red] — {skill_name!r}: {reason}")
        sys.exit(1)


@runtime.command("verify")
@click.argument("skill_name")
@click.argument("skill_path", type=click.Path(exists=True))
@click.pass_context
def runtime_verify(ctx, skill_name, skill_path):
    """Verify a skill's content matches its registered signature."""
    from agent_manager.core.signer import verify_signature

    mgr = _load_manager(ctx.obj["policy_path"])
    entry = mgr.get_skill(skill_name)

    if entry is None:
        err_console.print(f"[red]Skill {skill_name!r} not found in registry.[/red]")
        sys.exit(1)

    if not entry.signature:
        err_console.print(f"[yellow]Skill {skill_name!r} has no registered signature.[/yellow]")
        sys.exit(1)

    if verify_signature(skill_path, entry.signature):
        console.print(f"[green]VERIFIED[/green] — {skill_name!r} content matches registry signature")
    else:
        console.print(f"[bold red]TAMPERED[/bold red] — {skill_name!r} content does NOT match registered signature")
        sys.exit(2)


# --------------------------------------------------------------------------- #
# Helper                                                                        #
# --------------------------------------------------------------------------- #

def _resolve_skill(mgr, skill_id_or_name: str):
    """Resolve skill by full ID, short ID prefix, or name."""
    entry = mgr.get_skill(skill_id_or_name)
    if entry is None:
        # Try prefix match
        all_entries = mgr.list_skills()
        matches = [e for e in all_entries if e.skill_id.startswith(skill_id_or_name)]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            err_console.print(f"[red]Ambiguous ID prefix {skill_id_or_name!r} — matched {len(matches)} skills.[/red]")
            sys.exit(1)
        err_console.print(f"[red]Skill {skill_id_or_name!r} not found.[/red]")
        sys.exit(1)
    return entry


# --------------------------------------------------------------------------- #
# Prompt commands                                                               #
# --------------------------------------------------------------------------- #

@main.group()
def prompt():
    """Manage agent prompts: submit, list, show, deploy, retire."""


@prompt.command("submit")
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--name", default=None, help="Prompt name (derived from filename if omitted)")
@click.option("--agent", "agent_id", default="", help="Target agent ID")
@click.option("--description", default="", help="Human-readable description")
@click.option("--author", default=None, help="Submitter")
@click.option("--json", "output_json", is_flag=True, default=False, help="Output as JSON")
@click.pass_context
def prompt_submit(ctx, file_path, name, agent_id, description, author, output_json):
    """Submit a prompt file for vetting and registry."""
    mgr = _load_manager(ctx.obj.get("policy_path"))
    content = Path(file_path).read_text(encoding="utf-8")
    if not name:
        name = Path(file_path).stem

    entry = mgr.submit_prompt(
        name=name,
        content=content,
        agent_id=agent_id,
        description=description,
        author=author,
    )
    if not output_json:
        console.print(f"[bold]Submitted prompt [cyan]{name!r}[/cyan] — prompt_id={entry.prompt_id[:8]}…[/bold]")
        console.print(f"  Agent: {agent_id or '(unassigned)'}")
        console.print(f"  Status: {entry.status.value}")

    try:
        entry = mgr.vet_prompt(entry.prompt_id)
    except Exception as exc:
        if output_json:
            console.print_json(json.dumps(entry.model_dump(mode="json")))
        else:
            console.print(f"[yellow]Vetting skipped: {exc}[/yellow]")
        return

    if output_json:
        console.print_json(json.dumps(entry.model_dump(mode="json")))
    else:
        risk_color = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red", "EXTREME": "bold red"}.get(
            entry.risk_level.value if entry.risk_level else "LOW", "white"
        )
        console.print(f"  Risk: [{risk_color}]{entry.risk_level.value if entry.risk_level else 'N/A'}[/{risk_color}]")
        console.print(f"  Status after vetting: [{risk_color}]{entry.status.value}[/{risk_color}]")
        if entry.status.value == "VETTED":
            console.print(f"  [yellow]→ Prompt needs human review: agent-manager prompt approve {entry.prompt_id[:8]}[/yellow]")
        elif entry.status.value == "APPROVED":
            console.print(f"  [green]→ Auto-approved! Ready to deploy: agent-manager prompt deploy {entry.prompt_id[:8]}[/green]")
        elif entry.status.value == "REJECTED":
            console.print(f"  [red]→ Auto-rejected: {entry.rejection_reason or 'risk too high'}[/red]")


@prompt.command("list")
@click.option("--status", default=None, help="Filter by status")
@click.option("--agent", "agent_id", default=None, help="Filter by agent ID")
@click.option("--json", "output_json", is_flag=True, default=False)
@click.pass_context
def prompt_list(ctx, status, agent_id, output_json):
    """List prompts in the registry."""
    mgr = _load_manager(ctx.obj.get("policy_path"))
    status_enum = PromptStatus(status) if status else None
    entries = mgr.list_prompts(status=status_enum, agent_id=agent_id)

    if output_json:
        console.print_json(json.dumps([e.summary() for e in entries]))
        return

    if not entries:
        console.print("[dim]No prompts found.[/dim]")
        return

    table = Table(title="Prompt Registry", box=box.SIMPLE)
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Agent")
    table.add_column("Status")
    table.add_column("Risk")
    table.add_column("Submitted")
    for e in entries:
        risk_color = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red", "EXTREME": "bold red"}.get(
            e.risk_level.value if e.risk_level else "", ""
        )
        table.add_row(
            e.prompt_id[:8],
            e.name,
            e.agent_id or "-",
            e.status.value,
            f"[{risk_color}]{e.risk_level.value if e.risk_level else 'N/A'}[/{risk_color}]",
            e.submitted_at.strftime("%Y-%m-%d %H:%M") if e.submitted_at else "-",
        )
    console.print(table)


@prompt.command("show")
@click.argument("id_or_name")
@click.option("--json", "output_json", is_flag=True, default=False)
@click.pass_context
def prompt_show(ctx, id_or_name, output_json):
    """Show prompt details."""
    mgr = _load_manager(ctx.obj.get("policy_path"))
    entry = mgr.get_prompt(id_or_name)
    if not entry:
        err_console.print(f"[red]Prompt {id_or_name!r} not found.[/red]")
        sys.exit(1)

    if output_json:
        console.print_json(json.dumps(entry.model_dump(mode="json")))
        return

    console.print(Panel(f"[bold cyan]{entry.name}[/bold cyan]"))
    console.print(f"  Prompt ID:    {entry.prompt_id}")
    console.print(f"  Agent:        {entry.agent_id or '(unassigned)'}")
    console.print(f"  Description:  {entry.description or '-'}")
    console.print(f"  Status:       {entry.status.value}")
    if entry.risk_level:
        risk_color = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red", "EXTREME": "bold red"}[entry.risk_level.value]
        console.print(f"  Risk:         [{risk_color}]{entry.risk_level.value}[/{risk_color}]")
    if entry.signature:
        console.print(f"  Signature:    [dim]{entry.signature[:32]}…[/dim]")
    console.print(f"  Submitted:    {entry.submitted_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if entry.approved_at:
        console.print(f"  Approved:     {entry.approved_at.strftime('%Y-%m-%d %H:%M:%S')} by {entry.approved_by}")
    if entry.deployed_at:
        console.print(f"  Deployed:     {entry.deployed_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if entry.rejection_reason:
        console.print(f"  [red]Rejected: {entry.rejection_reason}[/red]")
    if entry.vetting:
        console.print(f"\n[bold]Vetting[/bold]")
        console.print(f"  Risk level:   {entry.vetting.risk_level.value}")
        console.print(f"  Findings:     {entry.vetting.findings_count}")
        console.print(f"  Analyzers:    {', '.join(entry.vetting.analyzers_used)}")
        if entry.vetting.policy_notes:
            for note in entry.vetting.policy_notes:
                console.print(f"  [yellow]• {note}[/yellow]")
    console.print(f"\n[bold]Content (first 500 chars)[/bold]")
    console.print(entry.content[:500])


@prompt.command("approve")
@click.argument("prompt_id")
@click.option("--approver", default="admin", help="Approver name")
@click.option("--note", default=None, help="Approval note")
@click.pass_context
def prompt_approve(ctx, prompt_id, approver, note):
    """Approve a VETTED prompt."""
    mgr = _load_manager(ctx.obj.get("policy_path"))
    try:
        entry = mgr.approve_prompt(prompt_id, approver, note)
        console.print(f"[green]Approved prompt {entry.name!r}[/green]")
        console.print(f"  Signature: [dim]{entry.signature[:32]}…[/dim]")
    except (KeyError, ValueError) as exc:
        err_console.print(f"[red]{exc}[/red]")
        sys.exit(1)


@prompt.command("reject")
@click.argument("prompt_id")
@click.option("--reviewer", default="admin", help="Reviewer name")
@click.option("--reason", default="Rejected by reviewer", help="Rejection reason")
@click.pass_context
def prompt_reject(ctx, prompt_id, reviewer, reason):
    """Reject a prompt."""
    mgr = _load_manager(ctx.obj.get("policy_path"))
    try:
        entry = mgr.reject_prompt(prompt_id, reviewer, reason)
        console.print(f"[yellow]Rejected prompt {entry.name!r}: {reason}[/yellow]")
    except (KeyError, ValueError) as exc:
        err_console.print(f"[red]{exc}[/red]")
        sys.exit(1)


@prompt.command("deploy")
@click.argument("prompt_id")
@click.option("--target-dir", default=None, help="Write prompt file to this directory")
@click.option("--actor", default=None, help="Actor performing deploy")
@click.pass_context
def prompt_deploy(ctx, prompt_id, target_dir, actor):
    """Deploy an APPROVED prompt — sign and optionally write to disk."""
    mgr = _load_manager(ctx.obj.get("policy_path"))
    try:
        entry = mgr.deploy_prompt(prompt_id, target_dir=target_dir, actor=actor)
        console.print(f"[green]Deployed prompt {entry.name!r}[/green]")
        if target_dir:
            console.print(f"  Written to: {target_dir}/{entry.name}.txt")
    except (KeyError, ValueError) as exc:
        err_console.print(f"[red]{exc}[/red]")
        sys.exit(1)


@prompt.command("retire")
@click.argument("id_or_name")
@click.option("--reason", default="Retired by operator", help="Retire reason")
@click.option("--actor", default=None)
@click.pass_context
def prompt_retire(ctx, id_or_name, reason, actor):
    """Retire a prompt — immediately revokes loadability."""
    mgr = _load_manager(ctx.obj.get("policy_path"))
    try:
        entry = mgr.retire_prompt(id_or_name, reason, actor)
        console.print(f"[yellow]Retired prompt {entry.name!r}: {reason}[/yellow]")
    except KeyError as exc:
        err_console.print(f"[red]{exc}[/red]")
        sys.exit(1)


@prompt.command("verify")
@click.argument("prompt_name")
@click.option("--file", "file_path", default=None, help="Local prompt file path to verify")
@click.pass_context
def prompt_verify(ctx, prompt_name, file_path):
    """Verify a local prompt file against the registry signature."""
    mgr = _load_manager(ctx.obj.get("policy_path"))
    result = mgr.verify_prompt_signature(
        prompt_name=prompt_name,
        local_file_path=Path(file_path) if file_path else None,
    )
    if result["valid"]:
        console.print(f"[green]VERIFIED[/green] — {prompt_name!r} signature matches registry")
    else:
        console.print(f"[bold red]FAILED[/bold red] — {result.get('reason', 'verification failed')}")
        sys.exit(2)
