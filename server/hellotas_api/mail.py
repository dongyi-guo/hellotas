"""Email: sign-in links, buddy introductions and the weekly digest, in English, Chinese and Nepali.

Backends: "console" prints messages to the log and keeps them in memory (development and tests), "smtp" sends
through any SMTP server (for example Gmail with an app password, or Office 365), and "resend" uses the Resend API.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger("hellotas_api.mail")
HOBART = ZoneInfo("Australia/Hobart")


@dataclass
class Message:
    to: str
    subject: str
    text: str
    headers: dict = field(default_factory=dict)


class Mailer:
    def __init__(self, settings):
        self.s = settings
        self.outbox: list[Message] = []  # console backend only

    def send(self, msg: Message) -> None:
        backend = self.s.email_backend
        if backend == "smtp":
            self._smtp(msg)
        elif backend == "resend":
            self._resend(msg)
        else:
            self.outbox.append(msg)
            log.info("EMAIL to %s: %s\n%s", msg.to, msg.subject, msg.text)

    def _smtp(self, msg: Message) -> None:
        em = EmailMessage()
        name, addr = parseaddr(self.s.email_from)
        em["From"] = formataddr((name, addr))
        em["To"] = msg.to
        em["Subject"] = msg.subject
        for key, value in msg.headers.items():
            em[key] = value
        em.set_content(msg.text)
        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if self.s.smtp_user:
                smtp.login(self.s.smtp_user, self.s.smtp_password)
            smtp.send_message(em)

    def _resend(self, msg: Message) -> None:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {self.s.resend_api_key}", "User-Agent": "hellotas-api/1.0"},
            json={"from": self.s.email_from, "to": [msg.to], "subject": msg.subject, "text": msg.text,
                  "headers": msg.headers},
            timeout=20,
        )
        resp.raise_for_status()


def _one_line(s: str) -> str:
    """Names and titles go into subjects: no line breaks (header injection), sensible length."""
    return " ".join(str(s).split())[:150]


T = {
    "en": {
        "login_subject": "Your sign-in link for Tasmania Welcome",
        "login": "Hello,\n\nUse this link to sign in to Tasmania Welcome. It works once, for {minutes} minutes:\n\n{link}\n\n"
                 "If you didn't ask for it, ignore this email; nobody can sign in without the link.\n",
        "ask_subject": "{name} would like to go to {event} with you",
        "ask": "Hello {to},\n\n{name} saw that you'd like company for {event} ({when}) and would like to go together.\n\n"
               "{message}\n\nAccept or decline on your account page:\n{link}\n\n"
               "Your email address stays private unless you accept.\n",
        "match_subject": "You're going to {event} together",
        "match": "Hello {to},\n\nYou and {other} are going to {event} ({when}) together.\n\n"
                 "Email {other}: {email}\n\nEvent details: {event_link}\n\n"
                 "Meet at the venue or another public place, and tell a friend where you'll be. Enjoy it.\n",
        "confirm_subject": "Confirm your weekly ICT events email",
        "confirm": "Hello,\n\nPlease confirm that you'd like a weekly email of ICT events for students in Tasmania:\n\n{link}\n\n"
                   "If you didn't ask for it, ignore this email and nothing will be sent.\n",
        "digest_subject": "ICT events for the next two weeks",
        "digest_intro": "Here's what's on for ICT students in Tasmania and online over the next two weeks. "
                        "Times are Hobart time.\n",
        "digest_none": "Nothing new in the next two weeks. See what's coming up later: {link}\n",
        "online": "Online",
        "digest_footer": "\nEverything on the site: {site}\nStop these emails: {unsubscribe}\n",
        "no_message": "",
    },
    "zh": {
        "login_subject": "你的塔斯马尼亚欢迎网站登录链接",
        "login": "你好，\n\n请用下面的链接登录塔斯马尼亚欢迎网站。链接只能使用一次，{minutes}分钟内有效：\n\n{link}\n\n"
                 "如果不是你本人申请的，请忽略这封邮件；没有这个链接，任何人都无法登录。\n",
        "ask_subject": "{name}想和你一起去{event}",
        "ask": "{to}你好，\n\n{name}看到你想找人一起去{event}（{when}），希望和你结伴同行。\n\n"
               "{message}\n\n请在你的账户页面接受或谢绝：\n{link}\n\n除非你接受，否则你的邮箱地址不会公开。\n",
        "match_subject": "你们将一起去{event}",
        "match": "{to}你好，\n\n你和{other}将一起去{event}（{when}）。\n\n{other}的邮箱：{email}\n\n活动详情：{event_link}\n\n"
                 "请在活动场地或其他公共场所见面，并告诉朋友你的去向。祝你玩得开心。\n",
        "confirm_subject": "请确认订阅每周ICT活动邮件",
        "confirm": "你好，\n\n请确认你希望每周收到一封面向塔斯马尼亚学生的ICT活动邮件：\n\n{link}\n\n"
                   "如果不是你本人申请的，请忽略这封邮件，我们不会再发送任何邮件。\n",
        "digest_subject": "未来两周的ICT活动",
        "digest_intro": "以下是未来两周塔斯马尼亚及线上面向ICT学生的活动。时间均为霍巴特时间。\n",
        "digest_none": "未来两周没有新活动。看看之后的安排：{link}\n",
        "online": "线上",
        "digest_footer": "\n网站上的全部活动：{site}\n退订这些邮件：{unsubscribe}\n",
        "no_message": "",
    },
    "ne": {
        "login_subject": "तस्मानियामा स्वागतमा साइन इन गर्ने लिङ्क",
        "login": "नमस्ते,\n\nतस्मानियामा स्वागतमा साइन इन गर्न यो लिङ्क प्रयोग गर्नुहोस्। यो एक पटक मात्र, {minutes} मिनेटसम्म चल्छ:\n\n"
                 "{link}\n\nतपाईंले माग्नुभएको होइन भने यो इमेल बेवास्ता गर्नुहोस्; लिङ्कबिना कसैले साइन इन गर्न सक्दैन।\n",
        "ask_subject": "{name} तपाईंसँग {event} जान चाहनुहुन्छ",
        "ask": "नमस्ते {to},\n\n{name} ले तपाईं {event} ({when}) मा कसैसँग जान चाहनुहुन्छ भन्ने देख्नुभयो र सँगै जान चाहनुहुन्छ।\n\n"
               "{message}\n\nआफ्नो खाता पृष्ठमा स्वीकार वा अस्वीकार गर्नुहोस्:\n{link}\n\n"
               "तपाईंले स्वीकार नगरेसम्म तपाईंको इमेल ठेगाना गोप्य रहन्छ।\n",
        "match_subject": "तपाईंहरू सँगै {event} जाँदै हुनुहुन्छ",
        "match": "नमस्ते {to},\n\nतपाईं र {other} सँगै {event} ({when}) जाँदै हुनुहुन्छ।\n\n{other} को इमेल: {email}\n\n"
                 "कार्यक्रमको विवरण: {event_link}\n\nकार्यक्रम स्थल वा अर्को सार्वजनिक ठाउँमा भेट्नुहोस्, र साथीलाई आफू कहाँ हुनुहुन्छ भनेर बताउनुहोस्।\n",
        "confirm_subject": "साप्ताहिक ICT कार्यक्रम इमेल पुष्टि गर्नुहोस्",
        "confirm": "नमस्ते,\n\nतस्मानियाका विद्यार्थीका लागि ICT कार्यक्रमहरूको साप्ताहिक इमेल चाहनुहुन्छ भने पुष्टि गर्नुहोस्:\n\n{link}\n\n"
                   "तपाईंले माग्नुभएको होइन भने यो इमेल बेवास्ता गर्नुहोस्, केही पठाइने छैन।\n",
        "digest_subject": "आगामी दुई हप्ताका ICT कार्यक्रम",
        "digest_intro": "तस्मानिया र अनलाइनमा ICT विद्यार्थीका लागि आगामी दुई हप्ताका कार्यक्रमहरू। समय होबार्टको हो।\n",
        "digest_none": "आगामी दुई हप्तामा नयाँ कार्यक्रम छैन। पछिका कार्यक्रम हेर्नुहोस्: {link}\n",
        "online": "अनलाइन",
        "digest_footer": "\nसाइटमा सबै कार्यक्रम: {site}\nयी इमेलहरू बन्द गर्नुहोस्: {unsubscribe}\n",
        "no_message": "",
    },
}

_WEEKDAYS = {"en": "Mon Tue Wed Thu Fri Sat Sun".split(), "zh": "周一 周二 周三 周四 周五 周六 周日".split(),
             "ne": "सोमबार मङ्गलबार बुधबार बिहीबार शुक्रबार शनिबार आइतबार".split()}
_MONTHS = {"en": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(),
           "ne": "जनवरी फेब्रुअरी मार्च अप्रिल मे जुन जुलाई अगस्ट सेप्टेम्बर अक्टोबर नोभेम्बर डिसेम्बर".split()}


def when(iso: str, lang: str = "en", all_day: bool = False) -> str:
    """'Thu 19 Nov, 5:15 pm' in Hobart time (or the Chinese and Nepali equivalents)."""
    try:
        dt = datetime.fromisoformat(iso).astimezone(HOBART)
    except (TypeError, ValueError):
        return iso or ""
    lang = lang if lang in T else "en"
    day = _WEEKDAYS[lang][dt.weekday()]
    if lang == "zh":
        text = f"{dt.month}月{dt.day}日（{day}）"
        return text if all_day else text + dt.strftime(" %H:%M")
    if lang == "ne":
        text = f"{_MONTHS['ne'][dt.month - 1]} {dt.day}, {day}"
        return text if all_day else text + dt.strftime(", %H:%M")
    text = f"{day} {dt.day} {_MONTHS['en'][dt.month - 1]}"
    return text if all_day else text + ", " + dt.strftime("%I:%M %p").lstrip("0").lower()


def text(lang: str, key: str, **values) -> str:
    lang = lang if lang in T else "en"
    return T[lang][key].format(**{k: (_one_line(v) if k in ("name", "to", "other", "event") else v)
                                  for k, v in values.items()})
