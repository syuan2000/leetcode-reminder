#!/usr/bin/env python3
"""Daily LeetCode spaced-repetition picker (matches the "Leetcode Problems" DB).

Queries the Notion database live, then:
  - NEW (2): walks the embedded NeetCode 150 roadmap and picks the first
    problems NOT already present in the Notion DB.
  - REVIEW (1): from problems already logged (with a "Confidence" value),
    picks the weakest + most overdue that is due by its confidence interval.

Writes a Markdown body to reminder_body.md and $GITHUB_STEP_SUMMARY, and sets
an issue_title output (the workflow opens a GitHub issue with it).

Required env:
  NOTION_TOKEN  - Notion internal integration token (share the DB with it)
  DATABASE_ID   - the Notion database id (f5d7bec9-7f97-827f-98b4-81da91df3164)

Notion schema this expects (edit CONFIG if you rename anything):
  Question     (title)                    - problem name
  Confidence   (select: Low / Med / High) - empty = logged but unrated
  Last Visited (date)                     - last time you touched it
"""

import os
import re
import json
import datetime
import urllib.request
import urllib.error

# ---------------- CONFIG ----------------
PROP_NAME = "Question"
PROP_CONF = "Confidence"
PROP_LASTVISIT = "Last Visited"

NEW_PER_DAY = 2
REVIEW_PER_DAY = 1

# Days before a problem is "due" for review again, by confidence.
INTERVAL = {"Low": 2, "Med": 7, "High": 30}
CONF_RANK = {"Low": 0, "Med": 1, "High": 2}

# NeetCode 150, in roadmap order. "New" picks walk this and skip anything
# already in your Notion DB.
NEETCODE_150 = [
    # Arrays & Hashing
    "Contains Duplicate", "Valid Anagram", "Two Sum", "Group Anagrams",
    "Top K Frequent Elements", "Encode and Decode Strings",
    "Product of Array Except Self", "Valid Sudoku", "Longest Consecutive Sequence",
    # Two Pointers
    "Valid Palindrome", "Two Sum II Input Array Is Sorted", "3Sum",
    "Container With Most Water", "Trapping Rain Water",
    # Sliding Window
    "Best Time to Buy and Sell Stock",
    "Longest Substring Without Repeating Characters",
    "Longest Repeating Character Replacement", "Permutation in String",
    "Minimum Window Substring", "Sliding Window Maximum",
    # Stack
    "Valid Parentheses", "Min Stack", "Evaluate Reverse Polish Notation",
    "Generate Parentheses", "Daily Temperatures", "Car Fleet",
    "Largest Rectangle in Histogram",
    # Binary Search
    "Binary Search", "Search a 2D Matrix", "Koko Eating Bananas",
    "Find Minimum in Rotated Sorted Array", "Search in Rotated Sorted Array",
    "Time Based Key Value Store", "Median of Two Sorted Arrays",
    # Linked List
    "Reverse Linked List", "Merge Two Sorted Lists", "Reorder List",
    "Remove Nth Node From End of List", "Copy List with Random Pointer",
    "Add Two Numbers", "Linked List Cycle", "Find the Duplicate Number",
    "LRU Cache", "Merge k Sorted Lists", "Reverse Nodes in k-Group",
    # Trees
    "Invert Binary Tree", "Maximum Depth of Binary Tree",
    "Diameter of Binary Tree", "Balanced Binary Tree", "Same Tree",
    "Subtree of Another Tree", "Lowest Common Ancestor of a Binary Search Tree",
    "Binary Tree Level Order Traversal", "Binary Tree Right Side View",
    "Count Good Nodes in Binary Tree", "Validate Binary Search Tree",
    "Kth Smallest Element in a BST",
    "Construct Binary Tree from Preorder and Inorder Traversal",
    "Binary Tree Maximum Path Sum",
    "Serialize and Deserialize Binary Tree",
    # Tries
    "Implement Trie Prefix Tree",
    "Design Add and Search Words Data Structure", "Word Search II",
    # Heap / Priority Queue
    "Kth Largest Element in a Stream", "Last Stone Weight",
    "K Closest Points to Origin", "Kth Largest Element in an Array",
    "Task Scheduler", "Design Twitter", "Find Median from Data Stream",
    # Backtracking
    "Subsets", "Combination Sum", "Permutations", "Subsets II",
    "Combination Sum II", "Word Search", "Palindrome Partitioning",
    "Letter Combinations of a Phone Number", "N-Queens",
    # Graphs
    "Number of Islands", "Max Area of Island", "Clone Graph",
    "Walls and Gates", "Rotting Oranges", "Pacific Atlantic Water Flow",
    "Surrounded Regions", "Course Schedule", "Course Schedule II",
    "Graph Valid Tree",
    "Number of Connected Components in an Undirected Graph",
    "Redundant Connection", "Word Ladder",
    # Advanced Graphs
    "Reconstruct Itinerary", "Min Cost to Connect All Points",
    "Network Delay Time", "Swim in Rising Water", "Alien Dictionary",
    "Cheapest Flights Within K Stops",
    # 1-D DP
    "Climbing Stairs", "Min Cost Climbing Stairs", "House Robber",
    "House Robber II", "Longest Palindromic Substring",
    "Palindromic Substrings", "Decode Ways", "Coin Change",
    "Maximum Product Subarray", "Word Break",
    "Longest Increasing Subsequence", "Partition Equal Subset Sum",
    # 2-D DP
    "Unique Paths", "Longest Common Subsequence",
    "Best Time to Buy and Sell Stock with Cooldown", "Coin Change II",
    "Target Sum", "Interleaving String",
    "Longest Increasing Path in a Matrix", "Distinct Subsequences",
    "Edit Distance", "Burst Balloons", "Regular Expression Matching",
    # Greedy
    "Maximum Subarray", "Jump Game", "Jump Game II", "Gas Station",
    "Hand of Straights", "Merge Triplets to Form Target Array",
    "Partition Labels", "Valid Parenthesis String",
    # Intervals
    "Insert Interval", "Merge Intervals", "Non-overlapping Intervals",
    "Meeting Rooms", "Meeting Rooms II",
    "Minimum Interval to Include Each Query",
    # Math & Geometry
    "Rotate Image", "Spiral Matrix", "Set Matrix Zeroes", "Happy Number",
    "Plus One", "Pow(x, n)", "Multiply Strings", "Detect Squares",
    # Bit Manipulation
    "Single Number", "Number of 1 Bits", "Counting Bits", "Reverse Bits",
    "Missing Number", "Sum of Two Integers", "Reverse Integer",
]
# ----------------------------------------

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
DATABASE_ID = os.environ["DATABASE_ID"]
TODAY = datetime.date.today()

API = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


def norm(s):
    """Normalize a title for fuzzy matching (lowercase, alnum only)."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def slug(name):
    """LeetCode URL slug from a problem name."""
    s = name.lower().replace("(", "").replace(")", "").replace(",", "")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def leetcode_url(name):
    return f"https://leetcode.com/problems/{slug(name)}/"


def query_all():
    rows = []
    payload = {"page_size": 100}
    while True:
        req = urllib.request.Request(
            API, data=json.dumps(payload).encode(), headers=HEADERS, method="POST"
        )
        try:
            with urllib.request.urlopen(req) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            raise SystemExit(f"Notion API error {e.code}: {e.read().decode()}")
        rows.extend(data["results"])
        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]
    return rows


def prop(page, name):
    return page.get("properties", {}).get(name)


def get_title(page):
    p = prop(page, PROP_NAME)
    if not p or not p.get("title"):
        return "(untitled)"
    return "".join(t["plain_text"] for t in p["title"]).strip()


def get_select(page, name):
    p = prop(page, name)
    if p and p.get("select"):
        return p["select"]["name"]
    return None


def get_date(page, name):
    p = prop(page, name)
    if p and p.get("date") and p["date"].get("start"):
        return datetime.date.fromisoformat(p["date"]["start"][:10])
    return None


def days_since(d):
    return (TODAY - d).days if d else 10_000  # never reviewed -> very overdue


def main():
    pages = query_all()

    solved_norm = set()
    studied = []
    for pg in pages:
        title = get_title(pg)
        solved_norm.add(norm(title))
        studied.append({
            "title": title,
            "conf": get_select(pg, PROP_CONF),
            "last": get_date(pg, PROP_LASTVISIT),
            "url": pg.get("url", ""),
        })

    # --- NEW picks: roadmap order, skip anything already in the DB ---
    news = []
    for name in NEETCODE_150:
        if norm(name) not in solved_norm:
            news.append(name)
        if len(news) >= NEW_PER_DAY:
            break

    # --- REVIEW picks: due, weakest & most overdue first ---
    def due(it):
        return days_since(it["last"]) >= INTERVAL.get(it["conf"], 3)

    rated = [it for it in studied if it["conf"]]
    review_pool = [it for it in rated if due(it)]
    if not review_pool:  # fall back to the oldest-touched logged problem
        review_pool = sorted(studied, key=lambda it: -days_since(it["last"]))
    review_pool.sort(key=lambda it: (CONF_RANK.get(it["conf"], 1), -days_since(it["last"])))
    reviews = review_pool[:REVIEW_PER_DAY]

    # --- Build body ---
    lines = [f"# LeetCode practice — {TODAY:%A, %b %d}", ""]
    lines.append("## New problems")
    if news:
        for name in news:
            lines.append(f"- [ ] [{name}]({leetcode_url(name)})")
    else:
        lines.append("- _Roadmap complete — every NeetCode 150 problem is logged. Nice._")
    lines.append("")
    lines.append("## Review (spaced repetition)")
    if reviews:
        for it in reviews:
            link = f"[{it['title']}]({it['url']})" if it["url"] else it["title"]
            n = days_since(it["last"])
            ago = "never" if n >= 10_000 else f"{n}d ago"
            conf = it["conf"] or "unrated"
            lines.append(f"- [ ] {link} — _{conf}, last {ago}_ · [solve]({leetcode_url(it['title'])})")
    else:
        lines.append("- _Nothing due for review today._")
    lines.append("")
    lines.append("> After each: update **Confidence** in Notion — "
                 "Low returns in days, Med in 7 days, High in a month.")

    body = "\n".join(lines)
    with open("reminder_body.md", "w") as f:
        f.write(body)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(body + "\n")

    title = f"LeetCode practice — {TODAY:%Y-%m-%d}"
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as f:
            f.write(f"issue_title={title}\n")

    print(body)


if __name__ == "__main__":
    main()
