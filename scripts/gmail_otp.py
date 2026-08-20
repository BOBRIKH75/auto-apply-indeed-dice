#!/usr/bin/env python3
"""
Gmail OTP Reader — reads Indeed verification codes from Gmail via IMAP.

Used by apply_indeed_auto.py to dynamically login to Indeed without
manual cookie refresh. Indeed sends a 6-digit code to your email,
this reads it within 30 seconds and returns it.

Requirements:
- GMAIL_USER: your gmail address (bobrikh75@gmail.com)
- GMAIL_APP_PASSWORD: Gmail App Password (not regular password)
"""

import imaplib
import email
import re
import time
import os
from datetime import datetime, timedelta


GMAIL_USER = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993


def read_indeed_otp(max_wait_seconds: int = 60, poll_interval: int = 5) -> str:
    """Poll Gmail for Indeed verification code. Returns the code or empty string.
    
    Searches for emails from Indeed with subject containing 'verification'
    or 'code' received in the last 2 minutes.
    """
    if not GMAIL_APP_PASSWORD:
        print("    ⚠️ GMAIL_APP_PASSWORD not set — cannot read OTP")
        return ""
    
    start_time = time.time()
    
    for attempt in range(max_wait_seconds // poll_interval):
        try:
            # Connect to Gmail IMAP
            mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
            mail.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            mail.select("INBOX")
            
            # Search for recent Indeed emails (last 2 minutes)
            # Indeed sends from: noreply@indeed.com or similar
            since_date = (datetime.now() - timedelta(minutes=3)).strftime("%d-%b-%Y")
            
            # Search criteria: from Indeed, recent
            search_queries = [
                f'(FROM "indeed" SINCE {since_date} UNSEEN)',
                f'(FROM "indeed.com" SINCE {since_date})',
                f'(SUBJECT "verification" SINCE {since_date})',
                f'(SUBJECT "code" FROM "indeed" SINCE {since_date})',
            ]
            
            for query in search_queries:
                try:
                    status, messages = mail.search(None, query)
                    if status != "OK":
                        continue
                    
                    msg_ids = messages[0].split()
                    if not msg_ids:
                        continue
                    
                    # Get the LATEST email (last one)
                    latest_id = msg_ids[-1]
                    status, msg_data = mail.fetch(latest_id, "(RFC822)")
                    if status != "OK":
                        continue
                    
                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)
                    
                    # Get email body
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                                break
                            elif part.get_content_type() == "text/html":
                                body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    else:
                        body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                    
                    # Also check subject
                    subject = str(msg.get("Subject", ""))
                    full_text = subject + " " + body
                    
                    # Extract 6-digit code
                    # Patterns Indeed uses: "123456", "123-456", "Your code is: 123456"
                    patterns = [
                        r'\b(\d{6})\b',          # Plain 6 digits
                        r'(\d{3}[-\s]\d{3})',     # 123-456 or 123 456
                        r'code[:\s]+(\d{6})',     # "code: 123456"
                        r'verification[:\s]+(\d{6})',  # "verification: 123456"
                    ]
                    
                    for pattern in patterns:
                        match = re.search(pattern, full_text)
                        if match:
                            code = match.group(1).replace("-", "").replace(" ", "")
                            if len(code) == 6 and code.isdigit():
                                mail.logout()
                                print(f"    ✅ OTP found: {code}")
                                return code
                
                except Exception:
                    continue
            
            mail.logout()
            
        except Exception as e:
            print(f"    ⚠️ Gmail IMAP error: {str(e)[:60]}")
        
        # Wait before next poll
        elapsed = time.time() - start_time
        if elapsed >= max_wait_seconds:
            break
        
        print(f"    ⏳ Waiting for Indeed OTP... ({int(elapsed)}s / {max_wait_seconds}s)")
        time.sleep(poll_interval)
    
    print(f"    ❌ OTP not found within {max_wait_seconds}s")
    return ""


if __name__ == "__main__":
    # Test: try to read any recent Indeed OTP
    code = read_indeed_otp(max_wait_seconds=10)
    if code:
        print(f"Found code: {code}")
    else:
        print("No code found (this is normal if Indeed didn't send one recently)")
