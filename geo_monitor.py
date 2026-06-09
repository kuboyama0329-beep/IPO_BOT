#!/usr/bin/env python3
"""
ゲオモバイル スマホ一覧監視スクリプト
価格変動・在庫切れ→再入荷をLINE通知する
"""

import os
import json
import re
import requests
from bs4 import BeautifulSoup
from linebot import LineBotApi
from linebot.models import TextSendMessage
from datetime import datetime

URL = "https://mvno.geo-mobile.jp/uqmobile/smartphone/"
STATE_FILE = "geo_state.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.co.jp/",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
}


# ── LINE送信 ──────────────────────────────────────────────

def send_line(message: str):
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("GEO_LINE_USER_ID")  # IPO BOTとは別の送り先
    if not token or not user_id:
        print("[WARN] LINE環境変数が未設定のため通知をスキップ")
        return
    try:
        api = LineBotApi(token)
        api.push_message(user_id, TextSendMessage(text=message))
        print(f"[LINE] 送信完了: {message[:60]}...")
    except Exception as e:
        print(f"[ERROR] LINE送信失敗: {e}")


# ── スクレイピング ────────────────────────────────────────

def normalize_price(text: str) -> str:
    """数字とカンマ・円だけ残して正規化"""
    if not text:
        return ""
    return re.sub(r"[^\d,円]", "", text.strip())


def is_out_of_stock(element) -> bool:
    """在庫切れ・売り切れ判定（複数パターンに対応）"""
    text = element.get_text(" ", strip=True)
    sold_out_keywords = ["売り切れ", "売切れ", "在庫なし", "在庫切れ", "SOLD OUT", "soldout", "完売"]
    return any(kw.lower() in text.lower() for kw in sold_out_keywords)


def scrape_products() -> list[dict]:
    """
    ゲオモバイルのスマホ一覧ページをスクレイピングして商品リストを返す。

    返り値の例:
    [
        {
            "name": "iPhone 15 128GB",
            "price": "49,800円",
            "in_stock": True,
            "url": "https://..."
        },
        ...
    ]
    """
    session = requests.Session()
    resp = session.get(URL, headers=HEADERS, timeout=30)

    if resp.status_code == 403:
        print(f"[ERROR] 403 Forbidden: サイトにアクセスを拒否されました (status={resp.status_code})")
        print("[INFO] GitHub ActionsのIPがブロックされている可能性があります")
        return []

    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")

    products = []

    # --- パターン1: li.p-item や div.item など一般的な商品カード ---
    # 実際のクラス名はサイトに合わせて調整が必要
    # デバッグ用に取得できたカード数を出力する
    candidates = (
        soup.select("li.p-item")          # よくあるパターン
        or soup.select("div.item")
        or soup.select("ul.products li")
        or soup.select(".product-list li")
        or soup.select(".item-list li")
        or soup.select("article.product")
        or soup.select(".smartphone-list .item")
        or soup.select(".product_list li")
    )

    print(f"[SCRAPE] 商品カード候補: {len(candidates)}件 (URL: {URL})")

    if not candidates:
        # フォールバック: <a> タグで商品リンクを探す
        print("[SCRAPE] カード要素が見つからずフォールバック処理へ")
        _debug_dump(soup)
        return []

    for card in candidates:
        # 商品名
        name_el = (
            card.select_one(".p-item__name")
            or card.select_one(".item-name")
            or card.select_one(".product-name")
            or card.select_one("h2")
            or card.select_one("h3")
            or card.select_one("h4")
        )
        name = name_el.get_text(strip=True) if name_el else ""

        # 価格
        price_el = (
            card.select_one(".p-item__price")
            or card.select_one(".price")
            or card.select_one(".item-price")
            or card.select_one('[class*="price"]')
        )
        price = normalize_price(price_el.get_text(strip=True)) if price_el else ""

        # 在庫
        in_stock = not is_out_of_stock(card)

        # 商品URL
        link_el = card.select_one("a[href]")
        product_url = ""
        if link_el:
            href = link_el["href"]
            product_url = href if href.startswith("http") else f"https://mvno.geo-mobile.jp{href}"

        if not name:
            continue

        products.append({
            "name": name,
            "price": price,
            "in_stock": in_stock,
            "url": product_url,
        })
        print(f"  [{'+' if in_stock else '-'}] {name} / {price}")

    return products


def _debug_dump(soup: BeautifulSoup):
    """スクレイピング失敗時にページ構造のヒントを出力"""
    print("[DEBUG] ページ内の主要クラス一覧（最大30件）:")
    seen = set()
    for tag in soup.find_all(True, limit=300):
        for cls in tag.get("class", []):
            if cls not in seen:
                seen.add(cls)
                if len(seen) <= 30:
                    print(f"  .{cls}")


# ── 状態管理 ─────────────────────────────────────────────

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(products: list[dict]):
    state = {p["name"]: {"price": p["price"], "in_stock": p["in_stock"]} for p in products}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f"[STATE] {STATE_FILE} を更新しました ({len(state)}件)")


# ── 差分検出 & 通知 ───────────────────────────────────────

def detect_changes(old: dict, new_products: list[dict]) -> list[str]:
    """変化があった商品のメッセージリストを返す"""
    messages = []

    for p in new_products:
        name = p["name"]
        old_entry = old.get(name)

        if old_entry is None:
            # 初回取得 or 新規商品 → 通知しない（初回登録のみ）
            continue

        # 価格変動
        if old_entry["price"] != p["price"] and p["price"]:
            messages.append(
                f"💰 価格変動\n"
                f"  {name}\n"
                f"  {old_entry['price']} → {p['price']}\n"
                f"  {p['url']}"
            )

        # 在庫切れ → 再入荷
        if not old_entry["in_stock"] and p["in_stock"]:
            messages.append(
                f"✅ 再入荷\n"
                f"  {name}\n"
                f"  価格: {p['price']}\n"
                f"  {p['url']}"
            )

        # 在庫あり → 在庫切れ（必要なら通知。コメントアウトで無効化可）
        # if old_entry["in_stock"] and not p["in_stock"]:
        #     messages.append(f"❌ 在庫切れ: {name}")

    return messages


# ── メイン ────────────────────────────────────────────────

def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] ゲオモバイル監視開始")

    old_state = load_state()
    is_first_run = len(old_state) == 0

    products = scrape_products()
    if not products:
        print("[WARN] 商品情報を取得できませんでした。スクレイピングの調整が必要です。")
        return

    if is_first_run:
        print(f"[INFO] 初回実行: {len(products)}件を記録しました（通知なし）")
        save_state(products)
        return

    changes = detect_changes(old_state, products)

    if changes:
        header = f"📱 ゲオモバイル 変更通知\n({now})\n\n"
        body = "\n\n".join(changes)
        send_line(header + body)
        print(f"[INFO] {len(changes)}件の変化を通知しました")
    else:
        print("[INFO] 変化なし")

    save_state(products)
    print(f"[{now}] ゲオモバイル監視完了")


if __name__ == "__main__":
    main()
