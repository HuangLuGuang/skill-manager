"""
Company skills deployment script.

Pulls all APPROVED/DEPLOYED skills from the registry and writes them to
the company-controlled skills directory.  Only CI/CD should run this.

Usage:
  python -m agent_manager.hooks.deploy --dest /usr/local/share/company-skills
  python -m agent_manager.hooks.deploy --dest /usr/local/share/company-skills --dry-run
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import click

from agent_manager.core.models import SkillStatus
from agent_manager.core.registry import Registry
from agent_manager.core.signer import verify_signature


@click.command()
@click.option("--dest", required=True, type=click.Path(),
              help="Destination directory (company-controlled skills dir)")
@click.option("--dry-run", is_flag=True, default=False,
              help="Print what would happen without making changes")
@click.option("--verify-sigs/--no-verify-sigs", default=True,
              help="Verify skill signatures before deploying (default: on)")
@click.option("--clean", is_flag=True, default=False,
              help="Remove skills from dest that are no longer in registry")
def main(dest: str, dry_run: bool, verify_sigs: bool, clean: bool):
    """Deploy all approved skills to the company skills directory."""
    dest_dir = Path(dest)
    registry = Registry()

    approved = registry.list_all(status=SkillStatus.APPROVED)
    deployed = registry.list_all(status=SkillStatus.DEPLOYED)
    loadable = approved + deployed

    if not loadable:
        click.echo("No approved/deployed skills in registry.")
        sys.exit(0)

    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    deployed_names: set[str] = set()
    errors: list[str] = []

    for entry in loadable:
        if not entry.skill_path:
            click.echo(f"  SKIP {entry.name!r} — no skill_path in registry entry", err=True)
            continue

        src = Path(entry.skill_path)
        if not src.exists():
            errors.append(f"{entry.name!r}: source path {entry.skill_path!r} does not exist")
            continue

        # Signature verification before deploying
        if verify_sigs and entry.signature:
            if not verify_signature(src, entry.signature):
                errors.append(
                    f"{entry.name!r}: signature mismatch — source files may have changed "
                    f"since approval. Re-submit and re-approve before deploying."
                )
                continue

        skill_dest = dest_dir / entry.name

        if dry_run:
            click.echo(f"  [dry-run] DEPLOY {entry.name!r}  {src} → {skill_dest}")
        else:
            if skill_dest.exists():
                shutil.rmtree(skill_dest)
            shutil.copytree(src, skill_dest)
            click.echo(f"  DEPLOYED {entry.name!r} → {skill_dest}")

        deployed_names.add(entry.name)

    # Optionally clean up skills no longer in registry
    if clean and dest_dir.exists():
        for child in dest_dir.iterdir():
            if child.is_dir() and child.name not in deployed_names:
                if dry_run:
                    click.echo(f"  [dry-run] REMOVE {child.name!r} (not in registry)")
                else:
                    shutil.rmtree(child)
                    click.echo(f"  REMOVED {child.name!r} (not in registry)")

    if errors:
        click.echo("\nErrors:", err=True)
        for e in errors:
            click.echo(f"  ERROR: {e}", err=True)
        sys.exit(1)

    # Write a manifest so the hook can quickly verify without reading each file
    manifest = {
        "skills": [
            {
                "name": e.name,
                "skill_id": e.skill_id,
                "risk_level": e.risk_level.value if e.risk_level else None,
                "approved_by": e.approved_by,
                "signature": e.signature,
            }
            for e in loadable
            if e.name in deployed_names
        ]
    }
    if not dry_run:
        (dest_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        click.echo(f"\nWrote manifest.json with {len(deployed_names)} skill(s).")

    click.echo(f"\nDone: {len(deployed_names)} skill(s) deployed to {dest_dir}")


if __name__ == "__main__":
    main()
