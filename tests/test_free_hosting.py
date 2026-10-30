#!/usr/bin/env python3
"""پشتیبانیِ «هاستِ رایگان» — render-free.yaml + keepalive + راهنما.

چرا تست دارد: پلنِ رایگانِ Render نه دیسک می‌دهد نه always-on. اگر کسی
`render-free.yaml` را دست بزند و مثلاً `disk:` یا `plan: starter` در آن
بماند، Blueprint بیلد نمی‌شود و کاربر فکر می‌کند «کد خراب است». همین‌طور
اگرワークflowِ بیدارنگه‌دار پاک/خاموش شود، سرویسِ رایگان بعد از ۱۵ دقیقه
می‌خوابد و ربات قطع می‌شود.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FAILED = []


def check(ok, label):
    print(("PASS  " if ok else "FAIL  ") + label, flush=True)
    if not ok:
        FAILED.append(label)
    return ok


def main():
    blue = REPO / "render-free.yaml"
    check(blue.exists(), "render-free.yaml در ریشه هست")
    t = blue.read_text(encoding="utf-8") if blue.exists() else ""
    check("plan: free" in t, "پلن = free")
    check(not re.search(r"^\s*disk:", t, re.M), "پلنِ رایگان بخشِ disk ندارد")
    check("runtime: docker" in t, "runtime = docker")
    check("dockerCommand: sh /opt/jafj/render-start.sh" in t, "همان entrypointِ رندر")
    check("healthCheckPath: /healthz" in t, "health check روی /healthz")
    check(re.search(r"key: DATA_DIR\s*\n\s*value: /data", t) is not None,
          "DATA_DIR=/data")
    check(re.search(r"key: DATA_GITHUB_TOKEN\s*\n\s*sync: false", t) is not None,
          "DATA_GITHUB_TOKEN به‌صورت secret (روی رایگان اجباری)")
    check(re.search(r"key: DATA_GITHUB_INTERVAL_MIN\s*\n\s*value: \"5\"", t)
          is not None, "سینکِ گیت‌هاب هر ۵ دقیقه (خوابِ ناگهانی)")
    check(re.search(r"key: BOT_TOKEN\s*\n\s*sync: false", t) is not None,
          "BOT_TOKEN به‌صورت secret")
    check("JAFJ_APP_SLEEPS" in t and "BACKUP_EVERY" in t,
          "پشتیبانِ کوتاه برای میزبانِ خواب‌دار")
    # دیسک نباید روی مسیر کد باشد (همان قاعده‌ی render.yaml)
    check(not re.search(r"mountPath:\s*/(app|opt/jafj)", t),
          "هیچ mountPath روی مسیرِ کد نیست")

    wf = REPO / ".github/workflows/keepalive.yml"
    check(wf.exists(), ".github/workflows/keepalive.yml هست")
    w = wf.read_text(encoding="utf-8") if wf.exists() else ""
    check("cron:" in w and "*/10" in w, "اجرای زمان‌بندی‌شده (هر ۱۰ دقیقه)")
    check("workflow_dispatch" in w, "اجرای دستی برای تست")
    check("secrets.HEALTH_URL" in w, "آدرس از secret HEALTH_URL می‌آید")
    check("healthz" in w, "به /healthz پینگ می‌کند")
    check("/healthz" in (REPO / "render-free.yaml").read_text(encoding="utf-8"),
          "همان مسیری که blueprint هلث‌چک می‌کند")
    # اسکریپتِ اجرا نباید آدرسِ هاردکد داشته باشد — وگرنه برای هر سرویسِ
    # دیگری بی‌فایده است (آدرسِ نمونه فقط داخلِ کامنتِ توضیحی مجاز است).
    body = w.split("run: |")[1] if "run: |" in w else w
    check(re.search(r"https?://", body) is None,
          "آدرس هاردکد نشده (فقط از HEALTH_URL)")

    doc = REPO / "FREE_HOSTING_FA.md"
    check(doc.exists(), "FREE_HOSTING_FA.md هست")
    d = doc.read_text(encoding="utf-8") if doc.exists() else ""
    for needle, label in [
        ("Render", "گزینه‌ی Render Free"),
        ("کارت بانکی", "هشدارِ کارت بانکی"),
        ("DATA_GITHUB_TOKEN", "اجباری‌بودنِ سینکِ گیت‌هاب"),
        ("keepalive", "بیدارنگه‌دارِ Actions"),
        ("cron-job.org", "جایگزینِ cron-job.org"),
        ("Oracle", "گزینه‌ی همیشه‌روشنِ Oracle"),
        ("/healthz", "راستی‌آزماییِ /healthz"),
        ("/version", "راستی‌آزماییِ /version"),
        ("Exit code 0", "خطای رایجِ Exit code 0"),
        ("render-free.yaml", "ارجاع به blueprintِ رایگان"),
    ]:
        check(needle in d, f"راهنما شاملِ: {label}")

    readme = (REPO / "README.md").read_text(encoding="utf-8")
    check("FREE_HOSTING_FA.md" in readme, "README به راهنما لینک می‌دهد")
    check("keepalive.yml" in readme, "README بیدارنگه‌دار را معرفی می‌کند")

    print()
    if FAILED:
        print("FAILED:", len(FAILED))
        for f in FAILED:
            print("  -", f)
        return 1
    print("ALL: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
