import click

from snuba import settings


@click.command()
@click.option("--bootstrap/--no-bootstrap", default=True)
@click.option("--workers/--no-workers", default=True)
def devserver(*, bootstrap: bool, workers: bool) -> None:
    "Starts all Snuba processes for local development."
    import os
    import sys
    from subprocess import call, list2cmdline

    from honcho.manager import Manager

    os.environ["PYTHONUNBUFFERED"] = "1"

    if bootstrap:
        cmd = ["snuba", "bootstrap", "--force", "--no-migrate"]
        if not workers:
            cmd.append("--no-kafka")
        returncode = call(cmd)
        if returncode > 0:
            sys.exit(returncode)

        # Run migrations
        returncode = call(["snuba", "migrations", "migrate", "--force"])
        if returncode > 0:
            sys.exit(returncode)

    daemons = [("api", ["snuba", "api"])]

    if not workers:
        os.execvp(daemons[0][1][0], daemons[0][1])

    daemons += [
        (
            "transaction-consumer",
            [
                "snuba",
                "consumer",
                "--auto-offset-reset=latest",
                "--no-strict-offset-reset",
                "--log-level=debug",
                "--storage=transactions",
                "--consumer-group=transactions_group",
            ],
        ),
        (
            "sessions-consumer",
            [
                "snuba",
                "consumer",
                "--auto-offset-reset=latest",
                "--no-strict-offset-reset",
                "--log-level=debug",
                "--storage=sessions_raw",
                "--consumer-group=sessions_group",
            ],
        ),
        (
            "outcomes-consumer",
            [
                "snuba",
                "consumer",
                "--auto-offset-reset=latest",
                "--no-strict-offset-reset",
                "--log-level=debug",
                "--storage=outcomes_raw",
                "--consumer-group=outcomes_group",
            ],
        ),
        (
            "consumer",
            [
                "snuba",
                "consumer",
                "--auto-offset-reset=latest",
                "--no-strict-offset-reset",
                "--log-level=debug",
                "--storage=errors",
            ],
        ),
        (
            "replacer",
            [
                "snuba",
                "replacer",
                "--auto-offset-reset=latest",
                "--no-strict-offset-reset",
                "--log-level=debug",
                "--storage=errors",
            ],
        ),
        (
            "cdc-consumer",
            [
                "snuba",
                "multistorage-consumer",
                "--auto-offset-reset=latest",
                "--no-strict-offset-reset",
                "--log-level=debug",
                "--storage=groupedmessages",
                "--storage=groupassignees",
                "--consumer-group=cdc_group",
            ],
        ),
    ]

    if settings.SEPARATE_SCHEDULER_EXECUTOR_SUBSCRIPTIONS_DEV:
        daemons += [
            (
                "subscriptions-scheduler-events",
                [
                    "snuba",
                    "subscriptions-scheduler",
                    "--entity=events",
                    "--consumer-group=snuba-events-subscriptions-scheduler",
                    "--followed-consumer-group=snuba-consumers",
                    "--auto-offset-reset=latest",
                    "--log-level=debug",
                    "--delay-seconds=1",
                    "--schedule-ttl=10",
                ],
            ),
            (
                "subscriptions-executor-events",
                [
                    "snuba",
                    "subscriptions-executor",
                    "--dataset=events",
                    "--entity=events",
                    "--consumer-group=snuba-events-subscription-executor",
                    "--auto-offset-reset=latest",
                ],
            ),
            (
                "subscriptions-scheduler-transactions",
                [
                    "snuba",
                    "subscriptions-scheduler",
                    "--entity=transactions",
                    "--consumer-group=snuba-transactions-subscriptions-scheduler",
                    "--followed-consumer-group=transactions_group",
                    "--auto-offset-reset=latest",
                    "--log-level=debug",
                    "--delay-seconds=1",
                    "--schedule-ttl=10",
                ],
            ),
            (
                "subscriptions-executor-transactions",
                [
                    "snuba",
                    "subscriptions-executor",
                    "--dataset=transactions",
                    "--entity=transactions",
                    "--consumer-group=snuba-transactions-subscription-executor",
                    "--auto-offset-reset=latest",
                ],
            ),
        ]

    else:
        daemons += [
            (
                "subscriptions-scheduler-executor-events",
                [
                    "snuba",
                    "subscriptions-scheduler-executor",
                    "--dataset=events",
                    "--entity=events",
                    "--consumer-group=snuba-events-subscriptions-scheduler-executor",
                    "--followed-consumer-group=snuba-consumers",
                    "--auto-offset-reset=latest",
                    "--no-strict-offset-reset",
                    "--log-level=debug",
                    "--delay-seconds=1",
                    "--schedule-ttl=10",
                    "--stale-threshold-seconds=900",
                ],
            ),
            (
                "subscriptions-scheduler-executor-transactions",
                [
                    "snuba",
                    "subscriptions-scheduler-executor",
                    "--dataset=transactions",
                    "--entity=transactions",
                    "--consumer-group=snuba-transactions-subscriptions-scheduler-executor",
                    "--followed-consumer-group=transactions_group",
                    "--auto-offset-reset=latest",
                    "--no-strict-offset-reset",
                    "--log-level=debug",
                    "--delay-seconds=1",
                    "--schedule-ttl=10",
                    "--stale-threshold-seconds=900",
                ],
            ),
        ]

    if settings.ENABLE_SENTRY_METRICS_DEV:
        daemons += [
            (
                "metrics-consumer",
                [
                    "snuba",
                    "consumer",
                    "--storage=metrics_raw",
                    "--auto-offset-reset=latest",
                    "--no-strict-offset-reset",
                    "--log-level=debug",
                    "--consumer-group=snuba-metrics-consumers",
                ],
            ),
            (
                "generic-metrics-distributions-consumer",
                [
                    "snuba",
                    "consumer",
                    "--storage=generic_metrics_distributions_raw",
                    "--auto-offset-reset=latest",
                    "--no-strict-offset-reset",
                    "--log-level=debug",
                    "--consumer-group=snuba-gen-metrics-distributions-consumers",
                ],
            ),
            (
                "generic-metrics-sets-consumer",
                [
                    "snuba",
                    "consumer",
                    "--storage=generic_metrics_sets_raw",
                    "--auto-offset-reset=latest",
                    "--no-strict-offset-reset",
                    "--log-level=debug",
                    "--consumer-group=snuba-gen-metrics-sets-consumers",
                ],
            ),
        ]
        if settings.ENABLE_METRICS_SUBSCRIPTIONS:
            if settings.SEPARATE_SCHEDULER_EXECUTOR_SUBSCRIPTIONS_DEV:
                daemons += [
                    (
                        "subscriptions-scheduler-metrics-counters",
                        [
                            "snuba",
                            "subscriptions-scheduler",
                            "--entity=metrics_counters",
                            "--consumer-group=snuba-metrics-subscriptions-scheduler",
                            "--followed-consumer-group=snuba-metrics-consumers",
                            "--auto-offset-reset=latest",
                            "--log-level=debug",
                            "--delay-seconds=1",
                            "--schedule-ttl=10",
                        ],
                    ),
                    (
                        "subscriptions-scheduler-metrics-sets",
                        [
                            "snuba",
                            "subscriptions-scheduler",
                            "--entity=metrics_sets",
                            "--consumer-group=snuba-metrics-subscriptions-scheduler",
                            "--followed-consumer-group=snuba-metrics-consumers",
                            "--auto-offset-reset=latest",
                            "--log-level=debug",
                            "--delay-seconds=1",
                            "--schedule-ttl=10",
                        ],
                    ),
                    (
                        "subscriptions-executor-metrics",
                        [
                            "snuba",
                            "subscriptions-executor",
                            "--dataset=metrics",
                            "--entity=metrics_counters",
                            "--entity=metrics_sets",
                            "--consumer-group=snuba-metrics-subscription-executor",
                            "--auto-offset-reset=latest",
                        ],
                    ),
                ]
            else:
                daemons += [
                    (
                        "subscriptions-scheduler-executor-metrics",
                        [
                            "snuba",
                            "subscriptions-scheduler-executor",
                            "--dataset=metrics",
                            "--entity=metrics_sets",
                            "--entity=metrics_counters",
                            "--consumer-group=snuba-metrics-subscriptions-scheduler-executor",
                            "--followed-consumer-group=snuba-metrics-consumers",
                            "--auto-offset-reset=latest",
                            "--no-strict-offset-reset",
                            "--log-level=debug",
                            "--delay-seconds=1",
                            "--schedule-ttl=10",
                        ],
                    ),
                ]

    if settings.ENABLE_PROFILES_CONSUMER:
        daemons += [
            (
                "profiles",
                [
                    "snuba",
                    "consumer",
                    "--auto-offset-reset=latest",
                    "--no-strict-offset-reset",
                    "--log-level=debug",
                    "--storage=profiles",
                ],
            ),
            (
                "functions",
                [
                    "snuba",
                    "consumer",
                    "--auto-offset-reset=latest",
                    "--no-strict-offset-reset",
                    "--log-level=debug",
                    "--storage=functions_raw",
                ],
            ),
        ]

    if settings.ENABLE_REPLAYS_CONSUMER:
        daemons += [
            (
                "replays-consumer",
                [
                    "snuba",
                    "consumer",
                    "--auto-offset-reset=latest",
                    "--log-level=debug",
                    "--storage=replays",
                ],
            ),
        ]

    manager = Manager()
    for name, cmd in daemons:
        manager.add_process(
            name,
            list2cmdline(cmd),
            quiet=False,
        )

    manager.loop()
    sys.exit(manager.returncode)
