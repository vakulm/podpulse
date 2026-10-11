"""PodPulse Interactive CLI Entrypoint with Human-in-the-Loop Confirmation Hook."""

import argparse
import asyncio
import sys
from src.agents.orchestrator import PodPulseCoordinator


def interactive_hitl_approval_prompt(formatted_brief: str) -> bool:
    """Explicit Human-in-the-Loop (HitL) code stop requiring confirmation before email dispatch."""
    print("\n" + "=" * 80)
    print("HUMAN-IN-THE-LOOP GATE: PREVIEW EXECUTIVE BRIEFING BEFORE EMAIL DISPATCH")
    print("=" * 80)
    print(formatted_brief)
    print("\n" + "-" * 80)
    if not sys.stdin.isatty():
        print("[HitL Non-Interactive Mode] Auto-approving for automated test run.")
        return True
    answer = input(
        "Approve and dispatch this briefing via email? [y/N]: "
    ).strip().lower()
    return answer in ("y", "yes")


async def run_cli() -> None:
    parser = argparse.ArgumentParser(
        description="PodPulse Multi-Agent Podcast Intelligence & Fact-Checker CLI"
    )
    parser.add_argument(
        "--url",
        default="sample://all-in-ep-200",
        help="YouTube episode URL or sample key (default: sample://all-in-ep-200)",
    )
    parser.add_argument(
        "--role",
        default="Enterprise AI & Cloud Leader",
        help="User role profile for tailored 'So What' insights",
    )
    parser.add_argument(
        "--email",
        default=None,
        help="Optional recipient email address (triggers Human-in-the-Loop confirmation)",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Bypass interactive prompt for automated CI evaluation",
    )
    args = parser.parse_args()

    coordinator = PodPulseCoordinator()
    callback = (
        (lambda _brief: True)
        if args.auto_approve
        else interactive_hitl_approval_prompt
    )

    result = await coordinator.run_episode_pipeline(
        video_url=args.url,
        user_role=args.role,
        recipient_email=args.email,
        approval_callback=callback if args.email else None,
    )

    if not result.success:
        print(f"\n[ERROR] Pipeline halted: {result.error_message}")
        sys.exit(1)

    if not args.email:
        print("\n" + result.formatted_brief)
    else:
        print(f"\n[DISPATCH RESULT] {result.email_dispatch_status}")


if __name__ == "__main__":
    asyncio.run(run_cli())
