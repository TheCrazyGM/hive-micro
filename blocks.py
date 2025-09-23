#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "hive-nectar",
#     "pymongo",
#     "bleach",
#     "lingua-language-detector",
#     "Markdown",
# ]
#
# [tool.uv.sources]
# hive-nectar = { git = "https://github.com/thecrazygm/hive-nectar" }
# ///

import hashlib
import html
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import bleach
from lingua import LanguageDetectorBuilder
from markdown import markdown
from nectar import Hive
from nectar.block import Blocks
from nectar.blockchain import Blockchain
from nectar.comment import Comment
from nectar.nodelist import NodeList
from pymongo import IndexModel, MongoClient
from pymongo.errors import BulkWriteError
from pymongo.operations import UpdateOne  # required by header deps

# Configuration
BATCH_SIZE = 1000  # Number of blocks to process at once
MAX_BULK_OPS = 500  # Maximum number of operations to send in one bulk write
SLEEP_TIME = 0.5  # Time to sleep between batches


def ensure_indexes(blocks_collection):
    """Ensure required indexes exist in the blocks collection."""
    blocks_collection.create_indexes(
        [
            IndexModel([("block_num", 1)]),  # For finding last processed block
            IndexModel(
                [("author", 1), ("permlink", 1)], unique=True
            ),  # For upsert operations
            IndexModel([("lang", 1)]),  # For querying by detected language
        ]
    )


def get_last_block(blocks_collection) -> int | None:
    """Get the last block number processed by finding the highest block_num in the database."""
    try:
        result = blocks_collection.find_one(
            {},
            sort=[("block_num", -1)],
            projection={"block_num": 1},
            hint=[("block_num", 1)],  # Force use of index
        )
        if result:
            return result["block_num"]
    except Exception as e:
        print(f"Error getting last block: {e}")
    return None


def process_operations(blocks_collection, operations: List[Dict]) -> None:
    """Process a batch of operations with error handling."""
    if not operations:
        return

    try:
        requests = [
            UpdateOne(
                {"author": op["author"], "permlink": op["permlink"]},
                {"$set": op},
                upsert=True,
            )
            for op in operations
        ]

        # Split into smaller batches if needed
        for i in range(0, len(requests), MAX_BULK_OPS):
            batch = requests[i : i + MAX_BULK_OPS]
            try:
                blocks_collection.bulk_write(batch, ordered=False)
            except BulkWriteError as bwe:
                print(f"Some operations in bulk write failed: {bwe.details}")

    except Exception as e:
        print(f"Error processing operations batch: {e}")


# MongoDB connection with connection pooling
client = MongoClient(
    "mongodb://localhost:27017/",
    maxPoolSize=10,
    waitQueueTimeoutMS=2000,
    connectTimeoutMS=2000,
)
db = client["blocks"]
blocks_collection = db["posts"]

# Ensure indexes exist (centralized helper)
ensure_indexes(blocks_collection)

# Manually updated list of nodes
nodelist = NodeList()
nodelist.update_nodes()
nodes = nodelist.get_nodes()

# Connect to Hive node
hive = Hive(node=nodes)
# genisys = 0
genisys = 41818753


def latest() -> int:
    """Get the current head block on the blockchain."""
    return Blockchain(blockchain_instance=hive).get_current_block().block_num


def get_last() -> int:
    """Get the last block number processed by finding the highest block_num in the database."""
    try:
        result = blocks_collection.find_one(
            {},
            sort=[("block_num", -1)],
            projection={"block_num": 1},
            hint=[("block_num", 1)],  # Force use of index
        )
        if result:
            return result["block_num"]
    except Exception as e:
        print(f"Error getting last block: {e}")
    print("[No blocks found, using first hive block.]")
    return genisys


def safe_str(value: Any, default: str = "") -> str:
    """Safely convert value to string."""
    try:
        if value is None:
            return default
        return str(value).strip()
    except Exception:
        return default


def safe_get(obj: Dict, key: str, default: Any = None) -> Any:
    """Safely get a value from a dictionary."""
    try:
        return obj.get(key, default)
    except Exception:
        return default


# Build lingua detector once (mirrors scrape.py behavior)
try:
    _LANG_DETECTOR = (
        LanguageDetectorBuilder.from_all_spoken_languages()
        .with_low_accuracy_mode()
        .build()
    )
except Exception:
    _LANG_DETECTOR = None


def _get_language_detector():
    return _LANG_DETECTOR


def _plain_text_for_lang(src: str) -> str:
    """Strip markdown/HTML and common noise (URLs, code, mentions) for language detection (matches scrape.py)."""
    if not src:
        return ""
    try:
        # Markdown -> HTML, then strip all tags
        html_from_md = markdown(src, output_format="html")
        text = bleach.clean(html_from_md, tags=[], attributes={}, strip=True)
        text = html.unescape(text)
        # Remove fenced code blocks and inline code remnants
        text = re.sub(r"```[\s\S]*?```", " ", text)
        text = re.sub(r"`[^`\n]+`", " ", text)
        # Remove standalone URLs and email-like strings
        text = re.sub(r"https?://\S+", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"www\.\S+", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", " ", text)
        # Remove obvious file links (images/docs)
        text = re.sub(
            r"\b\S+\.(?:png|jpe?g|gif|webp|svg|pdf|mp4|mov|avi)\b",
            " ",
            text,
            flags=re.IGNORECASE,
        )
        # Remove Markdown reference link definitions: [id]: url
        text = re.sub(r"^\s*\[[^\]]+\]:\s*\S+\s*$", " ", text, flags=re.MULTILINE)
        # Remove mentions and hashtags common in social text
        text = re.sub(r"(^|\s)@[A-Za-z0-9_./-]+", " ", text)
        text = re.sub(r"(^|\s)#[A-Za-z0-9_./-]+", " ", text)
        # Collapse remaining bracketed artifacts
        text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text)
        # Normalize whitespace
        text = " ".join(text.split())
        return text
    except Exception:
        return " ".join(src.split())


def _detect_language(
    plain_text: str,
) -> Tuple[str, Optional[float], Optional[List[Dict[str, float]]]]:
    """Detect language returning ISO-639-1 code (or 'und'), its confidence, and top-3 confidences list.

    Mirrors scrape.py semantics and structures.
    """
    lang_code: str = "und"
    lang_conf: Optional[float] = None
    lang_confidences: Optional[List[Dict[str, float]]] = None

    detector = _get_language_detector()
    if detector is None:
        return lang_code, lang_conf, lang_confidences

    try:
        # Short-text guard
        if len(plain_text) < 30 or len(plain_text.split()) < 5:
            return lang_code, lang_conf, lang_confidences

        detected = detector.detect_language_of(plain_text)
        conf_values = detector.compute_language_confidence_values(plain_text)

        # Build top-3 list
        top: List[Dict[str, float]] = []
        for cv in conf_values[:3]:
            lang_obj = getattr(cv, "language", None)
            v = float(getattr(cv, "value", 0.0))
            code = None
            if lang_obj is not None:
                iso1 = getattr(lang_obj, "iso_code_639_1", None)
                if iso1 is not None and getattr(iso1, "name", None):
                    code = iso1.name.lower()
            top.append({"code": code or "und", "value": v})

        lang_confidences = top if top else None

        if detected is not None:
            iso1 = getattr(detected, "iso_code_639_1", None)
            if iso1 is not None and getattr(iso1, "name", None):
                lang_code = iso1.name.lower()
            else:
                lang_code = "und"

        if detected is None and lang_confidences:
            lang_code = lang_confidences[0].get("code") or "und"

        if lang_confidences:
            match = next((c for c in lang_confidences if c["code"] == lang_code), None)
            lang_conf = (match or lang_confidences[0])["value"]
    except Exception:
        pass

    return lang_code, lang_conf, lang_confidences


# Main execution
try:
    current = latest()
    last = get_last_block(blocks_collection) or genisys
    variance = current - last
    print(f"{current=} {last=} {variance=}")

    # Calculate the number of rounds needed
    rounds = (variance // BATCH_SIZE) + 1

    for _r in range(rounds):
        start_time = time.time()
        blocks = Blocks(
            last + 1,
            BATCH_SIZE,
            only_ops=True,
            ops=["comment_operation"],
            blockchain_instance=hive,
        )
        operations = []
        num_coms = 0

        for block in blocks:
            last = block.block_num
            for operation in block.operations:
                if (
                    operation["type"] == "comment_operation"
                    and operation["value"]["parent_author"] == ""
                ):
                    # Parse JSON metadata once and cache results
                    metadata_str = operation["value"]["json_metadata"]
                    metadata = None

                    # Skip empty metadata
                    if not metadata_str or metadata_str.strip() in ["", "{}"]:
                        metadata = {}
                    else:
                        try:
                            # More targeted string cleaning - only clean if necessary
                            cleaned_str = metadata_str.strip()
                            # Handle escaped quotes if present
                            if cleaned_str.startswith('"') and cleaned_str.endswith(
                                '"'
                            ):
                                cleaned_str = cleaned_str[1:-1]
                            # Handle escaped backslashes
                            if "\\" in cleaned_str:
                                cleaned_str = cleaned_str.replace("\\", "")

                            metadata = json.loads(cleaned_str)
                        except (json.JSONDecodeError, ValueError):
                            metadata = {}

                    if not metadata:  # Skip if metadata is empty dict
                        continue

                    data = {
                        "block_num": block.block_num,
                        "permlink": operation["value"]["permlink"],
                        "tags": safe_get(metadata, "tags"),
                        "author": operation["value"]["author"],
                        "block_timestamp": block["timestamp"],
                        "title": operation["value"]["title"],
                        "app": safe_get(metadata, "app"),
                    }

                    # Extract images from metadata if available
                    images = safe_get(metadata, "image")
                    if images and isinstance(images, list) and images:
                        data["images"] = images

                    # Try to augment with additional data via Comment API
                    try:
                        authorperm = f"{data['author']}/{data['permlink']}"
                        try:
                            comment = Comment(authorperm, blockchain_instance=hive)
                        except Exception:
                            print("skipping comment")
                            comment = None

                        if comment:
                            # Extract created timestamp from comment
                            created_time = getattr(comment, "created", None)
                            if created_time:
                                data["timestamp"] = created_time
                            else:
                                # Fallback to block timestamp if comment created time not available
                                data["timestamp"] = data["block_timestamp"]

                            # Only process comment data if we don't have it from block
                            if not data.get("category") and getattr(
                                comment, "category", None
                            ):
                                data["category"] = comment.category

                            if not data.get("community") and getattr(
                                comment, "category", ""
                            ).startswith("hive-"):
                                data["community"] = comment.category

                            ct = getattr(comment, "community_title", None)
                            if ct and not data.get("community_title"):
                                data["community_title"] = ct

                            # Only process comment json_metadata if we don't have images
                            if "images" not in data:
                                comment_json_md = getattr(comment, "json_metadata", {})
                                if isinstance(comment_json_md, dict):
                                    comment_images = safe_get(comment_json_md, "image")
                                    if (
                                        comment_images
                                        and isinstance(comment_images, list)
                                        and comment_images
                                    ):
                                        data["images"] = comment_images

                            # Add body and computed fields if available
                            body = getattr(comment, "body", "") or ""
                            if body:
                                words = len(body.split())
                                read_time_sec = (
                                    int(round((words / 200.0) * 60)) if words else 0
                                )
                                body_hash = hashlib.sha256(
                                    body.encode("utf-8")
                                ).hexdigest()
                                data["body"] = body
                                data["body_length"] = len(body)
                                data["body_word_count"] = words
                                data["body_read_time_sec"] = read_time_sec
                                data["body_hash"] = body_hash
                                data["updated_at"] = time.time()

                                # Language detection (aligned with scrape.py)
                                try:
                                    plain_text = _plain_text_for_lang(body)
                                    lang, lang_conf, lang_confidences = (
                                        _detect_language(plain_text)
                                    )
                                    # Always set lang (may be 'und')
                                    data["lang"] = lang
                                    if lang_conf is not None:
                                        data["lang_conf"] = float(lang_conf)
                                    if lang_confidences is not None:
                                        data["lang_confidences"] = lang_confidences
                                except Exception:
                                    # Non-fatal: skip language fields on error
                                    pass
                        else:
                            # If comment couldn't be fetched, use block timestamp as fallback
                            data["timestamp"] = data["block_timestamp"]
                    except Exception as e:
                        print(f"Error fetching additional data for {authorperm}: {e}")
                        # Ensure timestamp is set even if comment processing fails
                        if "timestamp" not in data:
                            data["timestamp"] = data["block_timestamp"]

                    operations.append(data)
                    num_coms += 1

                    # Process in smaller batches if we've accumulated enough operations
                    if len(operations) >= MAX_BULK_OPS:
                        process_operations(blocks_collection, operations)
                        operations = []

        # Process any remaining operations
        process_operations(blocks_collection, operations)

        end_time = time.time()
        elapsed_time = end_time - start_time
        percentage_complete = ((last - genisys) / (current - genisys)) * 100
        print(
            f"{last}: {round(percentage_complete, 4)}% {len(blocks)} blocks: {num_coms} posts in {round(elapsed_time, 4)} seconds."
        )
        time.sleep(SLEEP_TIME)

except KeyboardInterrupt:
    print("\nGracefully shutting down...")
finally:
    client.close()  # Properly close MongoDB connection
