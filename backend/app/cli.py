"""Operator CLI: `python -m app.cli <command>`.

  create-user --email E --name N --role admin     (password read from THERMALTRACE_PASSWORD env or prompt)
  ingest [--window 24h|48h|7d]                     keyless FIRMS NRT poll, all sensors
  ingest-historical --source VIIRS_SNPP_SP --start 2025-07-01 --days 365  (needs FIRMS_MAP_KEY; fetched in 5-day windows)
  process [--all]                                  cluster + analyse events
  enrich [--limit 40]                              OSM / weather / imagery / geocode for top-priority events
  import-registry --source wri_gppd|gem|cea [--path F] [--version V] [--published YYYY-MM-DD]
  sync-facilities [--tiles 4]                      refresh the local OSM facility index (busiest 1° tiles first)
  train                                            train a LightGBM model (stored inactive; activate it from System health)
  load-demo                                        synthetic data (DEMO_MODE=true only)
"""
import argparse
import getpass
import json
import os
import sys
from datetime import date

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.security import hash_password, validate_password_strength
from app.db.session import SessionLocal
from app.models.auth import ROLES, User


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    configure_logging(settings.log_level)
    p = argparse.ArgumentParser(prog="thermaltrace")
    sub = p.add_subparsers(dest="cmd", required=True)
    cu = sub.add_parser("create-user")
    cu.add_argument("--email", required=True)
    cu.add_argument("--name", required=True)
    cu.add_argument("--role", choices=ROLES, default="analyst")
    ing = sub.add_parser("ingest")
    ing.add_argument("--window", default="24h", choices=["24h", "48h", "7d"])
    hist = sub.add_parser("ingest-historical")
    hist.add_argument("--source", required=True)
    hist.add_argument("--start", required=True)
    hist.add_argument("--days", type=int, default=5)
    pr = sub.add_parser("process")
    pr.add_argument("--all", action="store_true")
    en = sub.add_parser("enrich")
    en.add_argument("--limit", type=int, default=40)
    reg = sub.add_parser("import-registry")
    reg.add_argument("--source", required=True, choices=["wri_gppd", "gem", "cea"])
    reg.add_argument("--path")
    reg.add_argument("--version")
    reg.add_argument("--published")
    fs = sub.add_parser("sync-facilities")
    fs.add_argument("--tiles", type=int, default=4)
    sub.add_parser("train")
    sub.add_parser("load-demo")
    args = p.parse_args(argv)

    db = SessionLocal()
    try:
        if args.cmd == "create-user":
            password = os.environ.get("THERMALTRACE_PASSWORD") or getpass.getpass("Password: ")
            validate_password_strength(password)
            if db.execute(select(User).where(User.email == args.email.lower())).scalar_one_or_none():
                print("user already exists", file=sys.stderr)
                return 1
            db.add(User(email=args.email.lower(), full_name=args.name, password_hash=hash_password(password), role=args.role))
            db.commit()
            print(f"created {args.role} {args.email.lower()}")
        elif args.cmd == "ingest":
            from app.services.ingestion import ingest_firms_nrt

            _print(ingest_firms_nrt(db, window=args.window))
        elif args.cmd == "ingest-historical":
            from app.services.ingestion import ingest_firms_historical

            _print(ingest_firms_historical(db, args.source, args.start, args.days))
        elif args.cmd == "process":
            from app.processing.pipeline import process_new_detections
            from app.services.alerts import evaluate_rules

            total = {"passes": 0, "events_analysed": 0, "events_failed": 0, "alerts": 0}
            while True:  # one pass clusters up to 50,000 detections; continue until the backlog is empty
                res = process_new_detections(db, reanalyse_all=args.all and total["passes"] == 0)
                total["passes"] += 1
                total["events_analysed"] += res["events_analysed"]
                total["events_failed"] += res["events_failed"]
                total["alerts"] += evaluate_rules(db, res.pop("event_ids"))["alerts"]
                total["remaining_unassigned"] = res["remaining_unassigned"]
                if not res["remaining_unassigned"]:
                    break
            _print(total)
        elif args.cmd == "enrich":
            from app.services.enrichment import enrich_events, enrichment_priority

            _print(enrich_events(db, enrichment_priority(db, args.limit)))
        elif args.cmd == "import-registry":
            from app.services.registries_import import run_import

            _print(run_import(db, args.source, args.path, args.version,
                              date.fromisoformat(args.published) if args.published else None))
        elif args.cmd == "sync-facilities":
            from app.services.facility_sync import sync_tiles

            _print(sync_tiles(db, args.tiles))
        elif args.cmd == "train":
            from app.ml.registry import train_and_register

            mv = train_and_register(db)
            db.commit()
            _print({"model": mv.id, "active": mv.is_active, "label_provenance": mv.label_provenance, "metrics": {
                k: mv.metrics.get(k) for k in ("macro_f1_holdout", "n_train", "n_test", "caveat")}})
        elif args.cmd == "load-demo":
            from app.services.ingestion import load_demo_dataset

            _print(load_demo_dataset(db))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
