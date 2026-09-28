"""Weekly export of the service configuration as YAML."""

import anyio
import yaml
from vercel.cron import CronSchedule, cron

SCHEDULE = CronSchedule(minute=0, hour=6, day_of_week="mon")


@cron(SCHEDULE)
async def handler() -> dict[str, object]:
    document = {"schedule": str(SCHEDULE), "services": ["api", "reports"]}
    await anyio.sleep(0)
    return {"yaml": yaml.safe_dump(document, sort_keys=True), "roundtrip": yaml.safe_load(yaml.safe_dump(document))}
