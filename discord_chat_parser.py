#!/usr/bin/env python3
"""
Discrub Chat Export Parser
Parses exported Discrub JSON chat logs and renders them into a HTML page.

Usage:
    python discord_chat_parser.py <input_folder> [--output output.html]

    <input_folder> is the path to a DM folder like:
        carwarrantysalesperson_piqkZZM4y3/

    The script expects:
        - Page files: <folder>/<username>_page_1.json, <username>_page_2.json, ...
        - Emojis folder: emojis/
        - Avatars folder: avatars/
"""

import json
import os
import sys
import re
import glob
import argparse
import base64
from datetime import datetime, timezone
from pathlib import Path
from html import escape


# Helpers, these functions do what they are called, pretty self explanatory

def parse_timestamp(ts_str: str) -> datetime:
    ts_str = ts_str.replace("+00:00", "+0000").replace("Z", "+0000")
    try:
        return datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S.%f%z")
    except ValueError:
        return datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S%z")


def format_date_divider(dt: datetime) -> str:
    return dt.strftime("%B %d, %Y").replace(" 0", " ")


def format_timestamp(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{dt.month:02d}/{dt.day:02d}/{dt.year} {hour}:{dt.minute:02d} {ampm}"


def format_timestamp_short(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{hour}:{dt.minute:02d} {ampm}"


def should_group(prev_msg: dict | None, cur_msg: dict) -> bool:
    if prev_msg is None:
        return False
    if prev_msg["author"]["id"] != cur_msg["author"]["id"]:
        return False
    prev_dt = parse_timestamp(prev_msg["timestamp"])
    cur_dt = parse_timestamp(cur_msg["timestamp"])
    if (cur_dt - prev_dt).total_seconds() > 420:
        return False
    if cur_msg.get("type", 0) not in (0, 19):
        return False
    return True


# Content rendering

CUSTOM_EMOJI_RE = re.compile(r"<(a?):(\w+):(\d+)>")
USER_MENTION_RE = re.compile(r"<@!?(\d+)>")
CHANNEL_MENTION_RE = re.compile(r"<#(\d+)>")
ROLE_MENTION_RE = re.compile(r"<@&(\d+)>")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", re.DOTALL)
ITALIC2_RE = re.compile(r"_(.+?)_", re.DOTALL)
UNDERLINE_RE = re.compile(r"__(.+?)__", re.DOTALL)
STRIKE_RE = re.compile(r"~~(.+?)~~", re.DOTALL)
SPOILER_RE = re.compile(r"\|\|(.+?)\|\|", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`([^`]+?)`")
CODE_BLOCK_RE = re.compile(r"```(\w*)\n?(.*?)```", re.DOTALL)
URL_RE = re.compile(r"(https?://\S+)")


def render_content(content: str, mentions_list: list, emojis_dir: str) -> str:
    # Markdown to HTML
    if not content:
        return ""

    text = escape(content)

    # Code blocks (excluded from formatting)
    code_blocks = []

    def _save_code_block(m):
        lang = m.group(1)
        code = m.group(2)
        idx = len(code_blocks)
        code_blocks.append(f'<div class="code-block"><pre><code>{code}</code></pre></div>')
        return f"\x00CODEBLOCK{idx}\x00"

    text = CODE_BLOCK_RE.sub(_save_code_block, text)

    inline_codes = []

    def _save_inline_code(m):
        idx = len(inline_codes)
        inline_codes.append(f'<code class="inline-code">{m.group(1)}</code>')
        return f"\x00INLINECODE{idx}\x00"

    text = INLINE_CODE_RE.sub(_save_inline_code, text)

    # Custom emoji
    def _emoji_replace(m):
        animated = m.group(1) == "a"
        name = m.group(2)
        eid = m.group(3)
        ext = "gif" if animated else "png"
        local_path = os.path.join(emojis_dir, f"{eid}.{ext}")
        if not os.path.exists(local_path):
            alt_ext = "png" if animated else "gif"
            local_path = os.path.join(emojis_dir, f"{eid}.{alt_ext}")
        if os.path.exists(local_path):
            return (
                f'<img class="emoji" src="{local_path}" alt=":{name}:" '
                f'title=":{name}:" />'
            )
        return f":{name}:"

    text = CUSTOM_EMOJI_RE.sub(_emoji_replace, text)

    # Mentions
    mention_map = {}
    for m in mentions_list:
        uid = m.get("id", "")
        display = m.get("global_name") or m.get("username", "Unknown")
        mention_map[uid] = display

    def _user_mention(m):
        uid = m.group(1)
        name = mention_map.get(uid, "Unknown User")
        return f'<span class="mention">@{escape(name)}</span>'

    text = USER_MENTION_RE.sub(_user_mention, text)
    text = CHANNEL_MENTION_RE.sub(r'<span class="mention">#channel</span>', text)
    text = ROLE_MENTION_RE.sub(r'<span class="mention">@role</span>', text)

    # Markdown
    text = BOLD_RE.sub(r"<strong>\1</strong>", text)
    text = UNDERLINE_RE.sub(r"<u>\1</u>", text)
    text = ITALIC_RE.sub(r"<em>\1</em>", text)
    text = ITALIC2_RE.sub(r"<em>\1</em>", text)
    text = STRIKE_RE.sub(r"<del>\1</del>", text)
    text = SPOILER_RE.sub(
        r'<span class="spoiler" onclick="this.classList.toggle(\'revealed\')">\1</span>',
        text,
    )

    # URLs
    def _url_replace(m):
        url = m.group(1)
        if any(domain in url for domain in ("tenor.com", "giphy.com")):
            return f'<a class="embed-link" href="{url}" target="_blank">{url}</a>'
        return f'<a href="{url}" target="_blank">{url}</a>'

    text = URL_RE.sub(_url_replace, text)

    # Restore code
    for idx, block in enumerate(code_blocks):
        text = text.replace(f"\x00CODEBLOCK{idx}\x00", block)
    for idx, code in enumerate(inline_codes):
        text = text.replace(f"\x00INLINECODE{idx}\x00", code)

    # Newlines
    text = text.replace("\n", "<br/>")
    return text


def render_attachments(attachments: list) -> str:
    # Attachments duh
    if not attachments:
        return ""
    parts = []
    for att in attachments:
        filename = escape(att.get("filename", "file"))
        url = escape(att.get("url", ""))
        proxy = escape(att.get("proxy_url", url))
        content_type = att.get("content_type", "")
        width = att.get("width")
        height = att.get("height")

        if content_type and content_type.startswith("image/"):
            parts.append(
                f'<div class="attachment-image">'
                f'<a href="{url}" target="_blank">'
                f'<img src="{proxy}" alt="{filename}" '
                f'style="max-width:400px;max-height:300px;border-radius:8px;" />'
                f"</a></div>"
            )
        elif content_type and content_type.startswith("video/"):
            parts.append(
                f'<div class="attachment-video">'
                f'<video controls style="max-width:400px;border-radius:8px;">'
                f'<source src="{proxy}" type="{content_type}">'
                f"</video></div>"
            )
        elif content_type and content_type.startswith("audio/"):
            parts.append(
                f'<div class="attachment-audio">'
                f'<audio controls><source src="{proxy}" type="{content_type}"></audio>'
                f"</div>"
            )
        else:
            size = att.get("size", 0)
            size_str = (
                f"{size / 1024:.1f} KB" if size < 1_048_576 else f"{size / 1_048_576:.1f} MB"
            )
            parts.append(
                f'<div class="attachment-file">'
                f'<a href="{url}" target="_blank">📎 {filename}</a>'
                f' <span class="file-size">({size_str})</span></div>'
            )
    return "\n".join(parts)


def render_embeds(embeds: list) -> str:
    # Embeds
    if not embeds:
        return ""
    parts = []
    for embed in embeds:
        color = embed.get("color")
        border = f"border-left: 4px solid #{color:06x};" if color else ""
        title = escape(embed.get("title", ""))
        url = escape(embed.get("url", ""))
        description = escape(embed.get("description", ""))
        thumb = embed.get("thumbnail", {})
        thumb_url = escape(thumb.get("proxy_url", thumb.get("url", ""))) if thumb else ""

        html = f'<div class="embed" style="{border}">'
        if title:
            if url:
                html += f'<div class="embed-title"><a href="{url}" target="_blank">{title}</a></div>'
            else:
                html += f'<div class="embed-title">{title}</div>'
        if description:
            html += f'<div class="embed-description">{description}</div>'
        if thumb_url:
            html += (
                f'<img class="embed-thumbnail" src="{thumb_url}" '
                f'style="max-width:80px;max-height:80px;border-radius:4px;margin-top:8px;" />'
            )
        fields = embed.get("fields", [])
        if fields:
            html += '<div class="embed-fields">'
            for field in fields:
                inline = "inline" if field.get("inline") else ""
                html += (
                    f'<div class="embed-field {inline}">'
                    f'<div class="embed-field-name">{escape(field.get("name", ""))}</div>'
                    f'<div class="embed-field-value">{escape(field.get("value", ""))}</div>'
                    f"</div>"
                )
            html += "</div>"
        image = embed.get("image")
        if image:
            img_url = escape(image.get("proxy_url", image.get("url", "")))
            html += (
                f'<img class="embed-image" src="{img_url}" '
                f'style="max-width:400px;border-radius:4px;margin-top:8px;" />'
            )
        html += "</div>"
        parts.append(html)
    return "\n".join(parts)


def render_reactions(reactions: list, emojis_dir: str) -> str:
    # You get the point
    if not reactions:
        return ""
    parts = ['<div class="reactions">']
    for r in reactions:
        emoji = r.get("emoji", {})
        count = r.get("count", 1)
        eid = emoji.get("id")
        name = emoji.get("name", "?")
        if eid:
            animated = emoji.get("animated", False)
            ext = "gif" if animated else "png"
            local = os.path.join(emojis_dir, f"{eid}.{ext}")
            if os.path.exists(local):
                label = f'<img class="emoji" src="{local}" alt=":{name}:" />'
            else:
                label = f":{name}:"
        else:
            label = name
        parts.append(
            f'<span class="reaction"><span class="reaction-emoji">{label}</span>'
            f'<span class="reaction-count">{count}</span></span>'
        )
    parts.append("</div>")
    return "\n".join(parts)


def render_reply_header(msg: dict, all_messages_by_id: dict, emojis_dir: str) -> str:
    # Reply headers
    ref = msg.get("message_reference")
    if not ref:
        return ""
    ref_id = ref.get("message_id", "")
    ref_msg = all_messages_by_id.get(ref_id)
    if not ref_msg:
        return '<div class="reply-header">↩️ <em>Original message was deleted</em></div>'
    ref_author = ref_msg["author"]
    ref_display = ref_author.get("global_name") or ref_author.get("username", "Unknown")
    ref_content = ref_msg.get("content", "")
    if len(ref_content) > 120:
        ref_content = ref_content[:120] + "…"
    ref_content_html = escape(ref_content)
    return (
        f'<div class="reply-header">'
        f'<span class="reply-line"></span>'
        f'<span class="reply-author">{escape(ref_display)}</span> '
        f'<span class="reply-content">{ref_content_html}</span>'
        f"</div>"
    )


# System/special message types

MESSAGE_TYPE_LABELS = {
    1: "📌 {author} added a recipient.",
    2: "📌 {author} removed a recipient.",
    3: "📞 {author} started a call.",
    4: "✏️ {author} changed the channel name.",
    5: "✏️ {author} changed the channel icon.",
    6: "📌 {author} pinned a message.",
    7: "👋 {author} joined the server!",
    8: "🎉 {author} just boosted the server!",
    9: "🎉 {author} just boosted the server! (Tier 1)",
    10: "🎉 {author} just boosted the server! (Tier 2)",
    11: "🎉 {author} just boosted the server! (Tier 3)",
}


def get_system_message(msg: dict) -> str | None:
    mtype = msg.get("type", 0)
    template = MESSAGE_TYPE_LABELS.get(mtype)
    if template is None:
        return None
    author = msg["author"].get("global_name") or msg["author"].get("username", "Unknown")
    return template.format(author=escape(author))


# Avatar resolution

def resolve_avatar(author: dict, avatars_dir: str) -> str:
    """Return a path or data URI for the user's avatar.

    Lookup order:
        1. avatars/<userid>/<anything>.<image_ext>
        2. avatars/<userid>_<hash>.<ext>
        3. avatars/<userid>.<ext>
        4. avatars/<hash>.<ext>
        5. Default Discord CDN avatar
    """
    uid = author.get("id", "")
    avatar_hash = author.get("avatar", "")

    # 1 Subdirectory
    user_dir = os.path.join(avatars_dir, str(uid))
    if os.path.isdir(user_dir):
        for ext_pattern in ("*.jpeg", "*.jpg", "*.png", "*.gif", "*.webp"):
            matches = glob.glob(os.path.join(user_dir, ext_pattern))
            if matches:
                return matches[0]

    # 2 3 4 Flat file
    for name_candidate in [f"{uid}_{avatar_hash}", uid, avatar_hash]:
        if not name_candidate:
            continue
        for ext in ("png", "jpg", "jpeg", "gif", "webp"):
            p = os.path.join(avatars_dir, f"{name_candidate}.{ext}")
            if os.path.exists(p):
                return p

    # 5 Fallback
    disc = int(author.get("discriminator", "0") or "0")
    default_idx = disc % 5 if disc else int(uid) % 5 if uid.isdigit() else 0
    return f"https://cdn.discordapp.com/embed/avatars/{default_idx}.png"


def discover_pages(folder: str) -> list[str]:
    pattern = os.path.join(folder, "*_page_*.json")
    files = glob.glob(pattern)
    if not files:
        files = sorted(glob.glob(os.path.join(folder, "*.json")))
        return files

    def page_num(path: str) -> int:
        base = os.path.basename(path)
        m = re.search(r"_page_(\d+)\.json$", base)
        return int(m.group(1)) if m else 0

    files.sort(key=page_num)
    return files


def load_all_messages(folder: str) -> list[dict]:
    pages = discover_pages(folder)
    if not pages:
        print(f"Error: no page JSON files found in {folder}", file=sys.stderr)
        sys.exit(1)

    all_msgs = []
    for page_file in pages:
        with open(page_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                all_msgs.extend(data)
            elif isinstance(data, dict) and "messages" in data:
                all_msgs.extend(data["messages"])
            else:
                print(f"Warning: unexpected format in {page_file}", file=sys.stderr)

    all_msgs.sort(key=lambda m: m.get("timestamp", ""))
    return all_msgs


# HTML generation
# This was written by chatgpt because I am not touching "CSS"


CSS = r"""
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    background: #313338;
    color: #dbdee1;
    font-family: "gg sans", "Noto Sans", "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 16px;
    line-height: 1.375;
}
.container {
    max-width: 900px;
    margin: 0 auto;
    padding: 16px 0;
}
/* Channel header */
.channel-header {
    padding: 12px 16px;
    border-bottom: 1px solid #3f4147;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.channel-header .at-symbol {
    color: #80848e;
    font-size: 24px;
    font-weight: 600;
}
.channel-header .channel-name {
    font-size: 16px;
    font-weight: 600;
    color: #f2f3f5;
}
/* Date divider */
.date-divider {
    display: flex;
    align-items: center;
    margin: 16px 16px;
}
.date-divider .line {
    flex: 1;
    height: 1px;
    background: #3f4147;
}
.date-divider .date-text {
    padding: 0 8px;
    font-size: 12px;
    font-weight: 600;
    color: #80848e;
}
/* Messages */
.message-group {
    padding: 2px 48px 2px 72px;
    position: relative;
    min-height: 1.375em;
}
.message-group:hover {
    background: #2e3035;
}
.message-group.has-header {
    margin-top: 16px;
    padding-top: 2px;
}
.message-group .avatar {
    position: absolute;
    left: 16px;
    top: 2px;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    object-fit: cover;
    cursor: pointer;
}
.message-header {
    display: flex;
    align-items: baseline;
    gap: 8px;
}
.message-header .author-name {
    font-weight: 600;
    font-size: 16px;
    color: #f2f3f5;
    cursor: pointer;
}
.message-header .author-name:hover { text-decoration: underline; }
.message-header .timestamp {
    font-size: 12px;
    color: #80848e;
    font-weight: 400;
}
.message-header .clan-tag {
    font-size: 11px;
    color: #80848e;
    background: #2b2d31;
    padding: 0 4px;
    border-radius: 3px;
    font-weight: 500;
}
.message-header .edited {
    font-size: 10px;
    color: #80848e;
}
/* Grouped message (no header) */
.message-group.grouped {
    margin-top: 0;
    padding-top: 0;
}
.message-group.grouped .hover-timestamp {
    position: absolute;
    left: 0;
    width: 72px;
    text-align: center;
    font-size: 11px;
    color: #80848e;
    display: none;
    top: 4px;
}
.message-group.grouped:hover .hover-timestamp {
    display: block;
}
.message-content {
    color: #dbdee1;
    word-wrap: break-word;
    overflow-wrap: break-word;
}
.message-content a {
    color: #00a8fc;
    text-decoration: none;
}
.message-content a:hover { text-decoration: underline; }
/* Mention */
.mention {
    background: rgba(88, 101, 242, 0.3);
    color: #c9cdfb;
    padding: 0 2px;
    border-radius: 3px;
    font-weight: 500;
    cursor: pointer;
}
.mention:hover { background: rgba(88, 101, 242, 0.5); }
/* Spoiler */
.spoiler {
    background: #1e1f22;
    color: transparent;
    border-radius: 3px;
    padding: 0 4px;
    cursor: pointer;
    transition: background 0.1s, color 0.1s;
}
.spoiler.revealed { color: #dbdee1; background: rgba(255,255,255,0.1); }
/* Emoji */
.emoji {
    width: 22px;
    height: 22px;
    vertical-align: -0.4em;
    object-fit: contain;
}
/* Only emojis (large) */
.message-content.emoji-only .emoji {
    width: 48px;
    height: 48px;
}
/* Code */
.inline-code {
    background: #1e1f22;
    padding: 2px 4px;
    border-radius: 4px;
    font-family: Consolas, "Andale Mono", monospace;
    font-size: 14px;
}
.code-block {
    background: #1e1f22;
    border-radius: 4px;
    padding: 8px 12px;
    margin: 4px 0;
    overflow-x: auto;
}
.code-block pre { margin: 0; }
.code-block code {
    font-family: Consolas, "Andale Mono", monospace;
    font-size: 14px;
    color: #dbdee1;
}
/* Attachments */
.attachment-image { margin: 4px 0; }
.attachment-file {
    background: #2b2d31;
    padding: 8px 12px;
    border-radius: 8px;
    margin: 4px 0;
    display: inline-block;
    border: 1px solid #1e1f22;
}
.attachment-file a { color: #00a8fc; text-decoration: none; }
.attachment-file a:hover { text-decoration: underline; }
.file-size { color: #80848e; font-size: 12px; }
/* Embeds */
.embed {
    background: #2b2d31;
    padding: 8px 16px 8px 12px;
    border-radius: 4px;
    margin: 4px 0;
    max-width: 520px;
    border-left: 4px solid #1e1f22;
}
.embed-title { font-weight: 600; margin-bottom: 4px; }
.embed-title a { color: #00a8fc; text-decoration: none; }
.embed-title a:hover { text-decoration: underline; }
.embed-description { font-size: 14px; color: #dbdee1; }
.embed-fields { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
.embed-field { flex: 1 1 100%; }
.embed-field.inline { flex: 1 1 30%; }
.embed-field-name { font-size: 14px; font-weight: 600; color: #f2f3f5; }
.embed-field-value { font-size: 14px; color: #dbdee1; }
/* Reactions */
.reactions { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.reaction {
    background: #2b2d31;
    border: 1px solid #1e1f22;
    border-radius: 8px;
    padding: 2px 6px;
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 14px;
    cursor: pointer;
}
.reaction:hover { border-color: #80848e; }
.reaction-emoji { display: flex; align-items: center; }
.reaction-emoji .emoji { width: 18px; height: 18px; }
.reaction-count { color: #dbdee1; font-size: 13px; }
/* Reply header */
.reply-header {
    font-size: 14px;
    color: #80848e;
    margin-bottom: 2px;
    display: flex;
    align-items: center;
    gap: 4px;
    margin-left: -20px;
}
.reply-line {
    display: inline-block;
    width: 33px;
    height: 12px;
    border-left: 2px solid #4e5058;
    border-top: 2px solid #4e5058;
    border-radius: 8px 0 0 0;
    margin-right: 4px;
    vertical-align: bottom;
}
.reply-author { color: #f2f3f5; font-weight: 600; cursor: pointer; }
.reply-content { color: #80848e; cursor: pointer; }
.reply-content:hover { color: #dbdee1; }
/* System messages */
.system-message {
    padding: 4px 48px 4px 72px;
    font-size: 14px;
    color: #80848e;
}
.system-message:hover { background: #2e3035; }
/* Pinned / call icons */
.system-icon { margin-right: 4px; }
"""


def generate_html(
    messages: list[dict],
    folder: str,
    emojis_dir: str,
    avatars_dir: str,
) -> str:

    folder_base = os.path.basename(os.path.normpath(folder))
    parts = folder_base.rsplit("_", 1)
    channel_name = parts[0] if len(parts) == 2 else folder_base

    msg_by_id: dict[str, dict] = {m["id"]: m for m in messages}

    participants: dict[str, str] = {}
    for m in messages:
        a = m["author"]
        uid = a.get("id", "")
        if uid not in participants:
            participants[uid] = a.get("global_name") or a.get("username", "Unknown")

    html_parts: list[str] = []
    html_parts.append("<!DOCTYPE html>")
    html_parts.append('<html lang="en"><head><meta charset="utf-8"/>')
    html_parts.append(f"<title>Discord DM — {escape(channel_name)}</title>")
    html_parts.append(f"<style>{CSS}</style></head><body>")
    html_parts.append('<div class="container">')

    # Channel header
    html_parts.append('<div class="channel-header">')
    html_parts.append('<span class="at-symbol">@</span>')
    display_name = ", ".join(participants.values()) if len(participants) <= 4 else channel_name
    html_parts.append(f'<span class="channel-name">{escape(display_name)}</span>')
    html_parts.append("</div>")

    # Render messages
    prev_msg = None
    prev_date_str = None

    for msg in messages:
        dt = parse_timestamp(msg["timestamp"])
        date_str = format_date_divider(dt)

        if date_str != prev_date_str:
            html_parts.append(
                f'<div class="date-divider">'
                f'<div class="line"></div>'
                f'<span class="date-text">{date_str}</span>'
                f'<div class="line"></div></div>'
            )
            prev_date_str = date_str
            prev_msg = None

        sys_text = get_system_message(msg)
        if sys_text is not None:
            html_parts.append(f'<div class="system-message">{sys_text}</div>')
            prev_msg = msg
            continue

        grouped = should_group(prev_msg, msg)
        author = msg["author"]
        display = author.get("global_name") or author.get("username", "Unknown")
        avatar_src = resolve_avatar(author, avatars_dir)

        reply_html = render_reply_header(msg, msg_by_id, emojis_dir)

        content_html = render_content(
            msg.get("content", ""), msg.get("mentions", []), emojis_dir
        )

        raw = msg.get("content", "").strip()
        stripped = CUSTOM_EMOJI_RE.sub("", raw).strip()
        emoji_only = len(raw) > 0 and len(stripped) == 0

        content_class = "message-content emoji-only" if emoji_only else "message-content"

        attachments_html = render_attachments(msg.get("attachments", []))
        embeds_html = render_embeds(msg.get("embeds", []))
        reactions_html = render_reactions(msg.get("reactions", []), emojis_dir)

        edited = msg.get("edited_timestamp")
        edited_html = ' <span class="edited">(edited)</span>' if edited else ""

        clan = author.get("clan") or author.get("primary_guild")
        clan_html = ""
        if clan and clan.get("tag"):
            clan_html = f' <span class="clan-tag">{escape(clan["tag"])}</span>'

        if grouped:
            html_parts.append(f'<div class="message-group grouped">')
            html_parts.append(
                f'<span class="hover-timestamp">{format_timestamp_short(dt)}</span>'
            )
            if reply_html:
                html_parts.append(reply_html)
            html_parts.append(f'<div class="{content_class}">{content_html}{edited_html}</div>')
        else:
            html_parts.append(f'<div class="message-group has-header">')
            html_parts.append(
                f'<img class="avatar" src="{avatar_src}" alt="{escape(display)}" />'
            )
            if reply_html:
                html_parts.append(reply_html)
            html_parts.append('<div class="message-header">')
            html_parts.append(f'<span class="author-name">{escape(display)}</span>')
            html_parts.append(f'{clan_html}')
            html_parts.append(
                f'<span class="timestamp">{format_timestamp(dt)}</span>'
            )
            html_parts.append("</div>")
            html_parts.append(f'<div class="{content_class}">{content_html}{edited_html}</div>')

        html_parts.append(attachments_html)
        html_parts.append(embeds_html)
        html_parts.append(reactions_html)
        html_parts.append("</div>")  # .message-group

        prev_msg = msg

    html_parts.append("</div></body></html>")
    return "\n".join(html_parts)



# CLI


def main():
    parser = argparse.ArgumentParser(
        description="Parse Discord DM export JSON files into a Discord-like HTML view."
    )
    parser.add_argument(
        "input_folder",
        help="Path to the DM folder (e.g. kittycat_supreme_gata_piqkZZM4y3/)",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output HTML file path (default: <folder_name>.html)",
    )
    parser.add_argument(
        "--emojis", "-e",
        default=None,
        help="Path to the emojis folder (default: emojis/ next to the input folder)",
    )
    parser.add_argument(
        "--avatars", "-a",
        default=None,
        help="Path to the avatars folder (default: avatars/ next to the input folder)",
    )

    args = parser.parse_args()

    input_folder = args.input_folder.rstrip("/\\")
    parent_dir = os.path.dirname(os.path.abspath(input_folder))

    emojis_dir = args.emojis or os.path.join(parent_dir, "emojis")
    avatars_dir = args.avatars or os.path.join(parent_dir, "avatars")

    if not os.path.isdir(input_folder):
        print(f"Error: {input_folder} is not a directory.", file=sys.stderr)
        sys.exit(1)

    folder_name = os.path.basename(input_folder)
    output_path = args.output or f"{folder_name}.html"

    print(f"Input folder : {input_folder}")
    print(f"Emojis       : {emojis_dir}")
    print(f"Avatars      : {avatars_dir}")
    print(f"Output       : {output_path}")
    print()

    messages = load_all_messages(input_folder)
    print(f"✅ Loaded {len(messages)} messages from {len(discover_pages(input_folder))} page(s)")

    html = generate_html(messages, input_folder, emojis_dir, avatars_dir)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✅ Written to {output_path}")


if __name__ == "__main__":
    main()