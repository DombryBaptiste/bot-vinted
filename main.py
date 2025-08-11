#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Tuple

import requests
from vinted import Vinted  # pip install vinted-api-wrapper
from dotenv import load_dotenv


def read_queries(path: str) -> List[str]:
    """
    Lit un fichier texte; chaque ligne est :
      - une URL de recherche Vinted (ex: https://www.vinted.fr/vetements?...&order=newest_first)
      - OU une requête mots-clés (ex: "nike dunk 42")
    Lignes vides et commentaires (# ...) ignorés.
    """
    queries = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            queries.append(line)
    return queries


def ensure_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sent_items (
            item_id TEXT PRIMARY KEY,
            sent_at_utc TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def already_sent(conn: sqlite3.Connection, item_id: str) -> bool:
    cur = conn.execute("SELECT 1 FROM sent_items WHERE item_id = ?", (item_id,))
    return cur.fetchone() is not None


def mark_sent(conn: sqlite3.Connection, item_id: str):
    conn.execute(
        "INSERT OR IGNORE INTO sent_items (item_id, sent_at_utc) VALUES (?, ?)",
        (item_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def telegram_send_message(token: str, chat_id: str, text: str, disable_web_preview: bool = False):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true" if disable_web_preview else "false",
    }
    r = requests.post(url, data=payload, timeout=30)
    r.raise_for_status()


def telegram_send_photo(token: str, chat_id: str, photo_url: str, caption: Optional[str] = None):
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    payload = {
        "chat_id": chat_id,
        "photo": photo_url,
        "caption": caption or "",
        "parse_mode": "HTML",
    }
    r = requests.post(url, data=payload, timeout=30)
    # si échec (ex: photo invalide), on ne fait pas planter tout le script
    try:
        r.raise_for_status()
    except Exception:
        pass


def get_price(item) -> str:
    # Le wrapper expose généralement price et currency/total_item_price (dépend versions)
    price = getattr(item, "price", None) or getattr(item, "total_item_price", None) or ""

    return price.amount + " " + price.currency_code
    print(price.amount)
    try:
        # price peut être une str "35.0" -> on normalise
        price_val = float(str(price).replace(",", "."))
        return f"{price_val:.2f} €"
    except Exception:
        return str(price) if price else "—"


def get_photo_url(item) -> Optional[str]:
    # Item.photo peut être un objet avec .url ou .thumbnails
    photo = getattr(item, "photo", None)
    if not photo:
        return None
    # Essais défensifs
    for key in ("url", "full_url", "image_url", "small_url"):
        url = getattr(photo, key, None)
        if url:
            return url
    # parfois c'est un dict
    if isinstance(photo, dict):
        for key in ("url", "full_url", "image_url", "small_url"):
            if key in photo and photo[key]:
                return photo[key]
    return None


def build_caption(item) -> str:
    print(item)
    title = getattr(item, "title", "Sans titre")
    price = get_price(item)
    url = getattr(item, "url", "")

    bits = [f"<b>{title}</b>"]
    bits.append(f"<b>💴 Prix : {price}</b>")
    if url:
        bits.append(url)
        print("\n".join(bits))
    return "\n".join(bits)


def search_once(vinted: Vinted, q: str, per_page: int) -> Iterable:
    """
    Utilise vinted-api-wrapper.
    - Si q est une URL de recherche Vinted => on passe par 'url'
    - Sinon => 'query' mots-clés.
    Remarque : ajouter 'order=newest_first' dans vos URLs pour forcer le tri par nouveautés.
    """
    try:
        if q.startswith("http://") or q.startswith("https://"):
            # Beaucoup d'URLs Vinted supportent &order=newest_first pour les "dernières".
            resp = vinted.search(url=q, per_page=per_page)  # supporté par le wrapper
        else:
            # Recherche libre par mots-clés (vous pouvez ajuster d'autres filtres via kwargs si besoin)
            resp = vinted.search(query=q, per_page=per_page)
        items = getattr(resp, "items", None) or []
        return items
    except Exception as e:
        print(f"[WARN] Recherche échouée pour '{q}': {e}")
        return []


def main():
    parser = argparse.ArgumentParser(description="Vinted one-shot -> Telegram (avec dédup SQLite).")
    parser.add_argument("--file", "-f", required=True, help="Fichier texte avec une requête par ligne.")
    parser.add_argument("--db", default="vinted_seen.db", help="Chemin base sqlite (défaut: vinted_seen.db).")
    parser.add_argument("--per-page", type=int, default=20, help="Nb max d’items par requête (défaut: 20).")
    parser.add_argument("--sleep", type=float, default=1.2, help="Pause (s) entre requêtes pour rester poli (défaut: 1.2).")
    parser.add_argument("--domain", default=os.getenv("VINTED_DOMAIN", "fr"),
                        help="Domaine Vinted (fr, pl, de, ...). Défaut: env VINTED_DOMAIN ou 'fr'.")
    parser.add_argument("--no-photos", action="store_true", help="N’envoie que des messages texte (pas de sendPhoto).")

    args = parser.parse_args()

    # Secrets via env
    load_dotenv()

    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not tg_token or not tg_chat:
        raise SystemExit("Veuillez définir TELEGRAM_BOT_TOKEN et TELEGRAM_CHAT_ID dans l’environnement.")

    queries = read_queries(args.file)
    if not queries:
        print("Aucune requête à traiter.")
        return

    conn = ensure_db(args.db)
    vinted = Vinted(domain=args.domain)  # cf. doc PyPI: param 'domain' supporté
    total_sent = 0

    for q in queries:
        print(f"[INFO] Recherche: {q}")
        items = list(search_once(vinted, q, args.per_page))
        # On envoie du plus récent au plus ancien si l'URL inclut newest_first.
        for it in items:
            item_id = str(getattr(it, "id", ""))
            if not item_id:
                continue
            if already_sent(conn, item_id):
                continue

            caption = build_caption(it)
            photo_url = get_photo_url(it)

            # On tente d'abord la photo si autorisé, sinon message texte fallback
            if photo_url and not args.no_photos:
                telegram_send_photo(tg_token, tg_chat, photo_url, caption=caption)
            else:
                telegram_send_message(tg_token, tg_chat, caption, disable_web_preview=False)

            mark_sent(conn, item_id)
            total_sent += 1

        time.sleep(args.sleep)

    print(f"[OK] Terminé. Nouveaux éléments envoyés: {total_sent}")


if __name__ == "__main__":
    main()
