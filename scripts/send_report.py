#!/usr/bin/env python3
"""Send email report of today's applications."""

import json
import os
from datetime import datetime
from pathlib import Path

import requests

RESEND_KEY = os.environ.get("RESEND_KEY", "")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def main():
    indeed_results = []
    dice_results = []

    indeed_path = DATA_DIR / "apply_results_indeed.json"
    dice_path = DATA_DIR / "apply_results_dice.json"

    if indeed_path.exists():
        try:
            with open(indeed_path) as f:
                indeed_results = json.load(f)
        except (json.JSONDecodeError, Exception):
            indeed_results = []

    if dice_path.exists():
        try:
            with open(dice_path) as f:
                dice_results = json.load(f)
        except (json.JSONDecodeError, Exception):
            dice_results = []

    if not indeed_results and not dice_results:
        print("ℹ️ No results to report — both platforms returned empty")
        # Still send a notification
        indeed_results = []
        dice_results = []

    indeed_applied = [r for r in indeed_results if r["status"] == "submitted"]
    dice_applied = [r for r in dice_results if r["status"] == "submitted"]
    total_applied = len(indeed_applied) + len(dice_applied)

    today = datetime.now().strftime("%B %d, %Y")

    # Build HTML
    html = f"""
<html><body style="font-family:Arial;max-width:700px;margin:0 auto">
<div style="background:#28a745;color:white;padding:15px;border-radius:8px 8px 0 0">
  <h2 style="margin:0">✅ Applied to {total_applied} Jobs Today</h2>
  <p style="margin:3px 0 0;opacity:0.9">{today} | Indeed: {len(indeed_applied)} | Dice: {len(dice_applied)}</p>
</div>
<div style="padding:15px;border:1px solid #ddd">
"""

    if indeed_applied:
        html += "<h3>🔵 Indeed Applications</h3><table style='width:100%;border-collapse:collapse' border='1' bordercolor='#eee'>"
        html += "<tr style='background:#333;color:white'><th style='padding:6px'>Job</th><th style='padding:6px'>Company</th><th style='padding:6px'>Status</th></tr>"
        for r in indeed_applied:
            html += f"<tr><td style='padding:6px'><a href='{r['url']}'>{r['title'][:40]}</a></td><td style='padding:6px'>{r['company'][:25]}</td><td style='padding:6px;color:green'>✅ Applied</td></tr>"
        html += "</table>"

    if dice_applied:
        html += "<h3>🟠 Dice Applications</h3><table style='width:100%;border-collapse:collapse' border='1' bordercolor='#eee'>"
        html += "<tr style='background:#333;color:white'><th style='padding:6px'>Job</th><th style='padding:6px'>Company</th><th style='padding:6px'>Status</th></tr>"
        for r in dice_applied:
            html += f"<tr><td style='padding:6px'><a href='{r['url']}'>{r['title'][:40]}</a></td><td style='padding:6px'>{r['company'][:25]}</td><td style='padding:6px;color:green'>✅ Applied</td></tr>"
        html += "</table>"

    # Failed attempts
    failed_indeed = [r for r in indeed_results if r["status"] != "submitted"]
    failed_dice = [r for r in dice_results if r["status"] != "submitted"]

    if failed_indeed or failed_dice:
        html += f"<h3>⚠️ Not Applied ({len(failed_indeed) + len(failed_dice)} jobs)</h3>"
        html += "<p style='font-size:12px;color:#666'>These need manual apply — click the links:</p>"
        html += "<table style='width:100%;border-collapse:collapse;font-size:12px' border='1' bordercolor='#eee'>"
        for r in (failed_indeed + failed_dice)[:30]:
            html += f"<tr><td style='padding:4px'>{r['title'][:35]}</td><td style='padding:4px'>{r['company'][:20]}</td><td style='padding:4px'>{r['status']}</td><td style='padding:4px'><a href='{r['url']}' style='background:#007bff;color:white;padding:2px 6px;border-radius:3px;text-decoration:none;font-size:11px'>APPLY</a></td></tr>"
        html += "</table>"

    html += f"""
<h3>📊 Summary</h3>
<table style="font-size:14px">
<tr><td>Indeed attempted:</td><td><b>{len(indeed_results)}</b></td></tr>
<tr><td>Indeed applied:</td><td style="color:green"><b>{len(indeed_applied)}</b></td></tr>
<tr><td>Dice attempted:</td><td><b>{len(dice_results)}</b></td></tr>
<tr><td>Dice applied:</td><td style="color:green"><b>{len(dice_applied)}</b></td></tr>
<tr><td><b>TOTAL APPLIED:</b></td><td style="color:green;font-size:18px"><b>{total_applied}</b></td></tr>
</table>
<p style="font-size:11px;color:#999;margin-top:20px">Auto-Apply Bot | Runs daily at 11:00 AM MT</p>
</div></body></html>
"""

    if not RESEND_KEY or not RESEND_KEY.strip().startswith("re_"):
        print("⚠️ RESEND_KEY not set or invalid — report saved locally only")
        report_path = DATA_DIR / "last_report.html"
        with open(report_path, "w") as f:
            f.write(html)
        print(f"Saved to {report_path}")
        return

    # Clean the key (remove any whitespace/newlines)
    clean_key = RESEND_KEY.strip()

    # Send email
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {clean_key}", "Content-Type": "application/json"},
        json={
            "from": "Auto-Apply Bot <onboarding@resend.dev>",
            "to": ["bobrikh75@gmail.com"],
            "subject": f"✅ Applied to {total_applied} Jobs | Indeed {len(indeed_applied)} + Dice {len(dice_applied)} | {datetime.now().strftime('%b %d')}",
            "html": html,
        },
    )
    if resp.status_code == 200:
        print(f"📧 Email sent! Applied to {total_applied} jobs total")
    else:
        print(f"❌ Email failed: {resp.status_code} {resp.text[:100]}")


if __name__ == "__main__":
    main()
