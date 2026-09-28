"""CLI commands for independent snapshot debugging, simulation and service mode."""

import argparse
import asyncio
import json
from pathlib import Path
from .config import Config


async def execute(args):
    config = Config.load(args.config)
    if args.command == "retry-scene":
        from .evaluation.retries import run_scene

        report = await run_scene(
            args.artifact,
            config,
            args.output,
            args.steps,
            rewind_steps=args.rewind_steps,
            max_retries=args.max_retries,
            seed_log=args.seed_log,
        )
        print(json.dumps(report, indent=2))
        return
    if args.command == "snapshot":
        from .integration.alpasim_adapter import AlpasimAdapter
        from .state.state_builder import JevStateBuilder

        a = AlpasimAdapter(args.artifact, config, args.signal_annotations)
        t = a.artifact.rig.trajectory.time_range_us.start + round(
            args.start_offset * 1e6
        )
        snapshot = a.snapshot("snapshot-preview", t, 0)
        p = Path(args.output)
        p.mkdir(parents=True, exist_ok=True)
        (p / "snapshot.json").write_text(
            json.dumps(snapshot.as_dict(), allow_nan=False)
        )
        envelope = JevStateBuilder(config).build(snapshot)
        (p / "state.json").write_text(json.dumps(envelope, indent=2, allow_nan=False))
        print(f"Snapshot saved: {p}")
        return
    if args.command == "bev":
        from .visualization.bev import export

        print(f"Exported {export(args.log,args.output)} frames")
        return
    if args.command == "rebuild-state":
        from .state.snapshot import SceneSnapshot
        from .state.state_builder import JevStateBuilder

        snapshot = SceneSnapshot.from_dict(json.loads(Path(args.snapshot).read_text()))
        Path(args.output).write_text(
            json.dumps(
                JevStateBuilder(config).build(snapshot), indent=2, allow_nan=False
            )
        )
        return
    from .policy.client_factory import create_client

    from .logging.decision_log import DecisionLog

    api_log = DecisionLog(args.output)
    client = create_client(config, on_event=api_log.write)
    try:
        if args.command in {"simulate", "native-simulate"}:
            from .integration.local_simulation import run

            if args.command == "native-simulate":
                from .integration.native_simulation import run as native_run
            report = (
                await native_run(
                    args.artifact,
                    config,
                    client,
                    args.output,
                    args.steps,
                    args.signal_annotations,
                )
                if args.command == "native-simulate"
                else await run(
                    args.artifact,
                    config,
                    client,
                    args.output,
                    args.steps,
                    args.start_offset,
                    args.signal_annotations,
                )
            )
            print(json.dumps(report, indent=2))
            from .visualization.bev import export

            export(Path(args.output) / "decisions.jsonl", Path(args.output) / "bev")
        elif args.command == "serve":
            from .logging.decision_log import DecisionLog
            from .policy.jev_model import JevModel
            from .integration.driver_service import serve

            await serve(
                JevModel(config, client, DecisionLog(args.output)), args.host, args.port
            )
    finally:
        await client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("snapshot", "simulate", "native-simulate"):
        p = sub.add_parser(command)
        p.add_argument("--artifact", required=True)
        p.add_argument("--output", required=True)
        if command != "native-simulate":
            p.add_argument("--start-offset", type=float, default=1.0)
        p.add_argument("--signal-annotations")
        if command in {"simulate", "native-simulate"}:
            p.add_argument("--steps", type=int, default=10)
    p = sub.add_parser("retry-scene")
    p.add_argument("--artifact", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--steps", type=int, required=True)
    p.add_argument("--rewind-steps", type=int, default=5)
    p.add_argument("--max-retries", type=int, default=3)
    p.add_argument("--seed-log")
    p = sub.add_parser("serve")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=6789)
    p.add_argument("--output", required=True)
    p = sub.add_parser("bev")
    p.add_argument("--log", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("rebuild-state")
    p.add_argument("--snapshot", required=True)
    p.add_argument("--output", required=True)
    asyncio.run(execute(parser.parse_args()))


if __name__ == "__main__":
    main()
