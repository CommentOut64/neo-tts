from __future__ import annotations

import re

_SEGMENT_CLOSER_CHARACTERS = frozenset(('”', "’", '"', ")", "）", "]", "】", ">", "》", "」", "』", "〉", "〕", "｝", "｠"))


def normalize_whitespace(text: str) -> str:
    return re.sub(r" {2,}", " ", text).strip()


def is_decimal_dot_at(text: str, index: int) -> bool:
    return (
        0 < index < len(text) - 1
        and text[index] == "."
        and text[index - 1].isdigit()
        and text[index + 1].isdigit()
    )


def split_text_segments(text: str, min_segment_length: int = 10) -> list[str]:
    text = text.strip("\n")
    if not text:
        return []

    sentence_delimiters = r"([。！？.!?…\n])"
    parts = re.split(sentence_delimiters, text)

    sentences: list[str] = []
    for idx in range(0, len(parts) - 1, 2):
        sentences.append(parts[idx] + parts[idx + 1])
    if len(parts) % 2 == 1:
        sentences.append(parts[-1])

    cleaned = [item.strip() for item in sentences if item.strip()]
    merged: list[str] = []
    current = ""
    for sentence in cleaned:
        if len(current) + len(sentence) < min_segment_length:
            current += sentence
            continue
        if current:
            merged.append(current)
        current = sentence
    if current:
        merged.append(current)
    return merged


OFFICIAL_SPLIT_PUNCTUATION = {
    "，",
    "。",
    "？",
    "！",
    ",",
    ".",
    "?",
    "!",
    "~",
    ":",
    "：",
    "—",
    "…",
}

OFFICIAL_CUT5_PUNCTUATION = {",", ".", ";", "?", "!", "、", "，", "。", "？", "！", "：", "…"}
OFFICIAL_EMPTY_SEGMENT_PUNCTUATION = {"!", "?", "…", ",", ".", "-", " "}


def _official_split_sentence_units(text: str) -> list[str]:
    text = text.replace("……", "。").replace("——", "，")
    if text and text[-1] not in OFFICIAL_SPLIT_PUNCTUATION:
        text += "。"

    head = 0
    tail = 0
    units: list[str] = []
    while head < len(text):
        if text[head] in OFFICIAL_SPLIT_PUNCTUATION:
            head += 1
            head = _consume_following_closer_characters(text, head)
            units.append(text[tail:head])
            tail = head
            continue
        head += 1
    return units


def _official_cut0(text: str) -> str:
    return text if not set(text).issubset(OFFICIAL_EMPTY_SEGMENT_PUNCTUATION) else "\n"


def _official_cut1(text: str) -> str:
    text = text.strip("\n")
    units = _official_split_sentence_units(text)
    split_idx = list(range(0, len(units), 4))
    if split_idx:
        split_idx[-1] = None
    if len(split_idx) > 1:
        pieces = []
        for index in range(len(split_idx) - 1):
            pieces.append("".join(units[split_idx[index] : split_idx[index + 1]]))
    else:
        pieces = [text]
    pieces = [item for item in pieces if not set(item).issubset(OFFICIAL_EMPTY_SEGMENT_PUNCTUATION)]
    return "\n".join(pieces)


def _official_cut2(text: str) -> str:
    text = text.strip("\n")
    units = _official_split_sentence_units(text)
    if len(units) < 2:
        return text

    pieces: list[str] = []
    char_sum = 0
    chunk = ""
    for unit in units:
        char_sum += len(unit)
        chunk += unit
        if char_sum > 50:
            char_sum = 0
            pieces.append(chunk)
            chunk = ""

    if chunk:
        pieces.append(chunk)

    if len(pieces) > 1 and len(pieces[-1]) < 50:
        pieces[-2] = pieces[-2] + pieces[-1]
        pieces = pieces[:-1]

    pieces = [item for item in pieces if not set(item).issubset(OFFICIAL_EMPTY_SEGMENT_PUNCTUATION)]
    return "\n".join(pieces)


def _official_cut3(text: str) -> str:
    text = text.strip("\n")
    pieces = [item for item in text.strip("。").split("。") if not set(item).issubset(OFFICIAL_EMPTY_SEGMENT_PUNCTUATION)]
    return "\n".join(pieces)


def _official_cut4(text: str) -> str:
    text = text.strip("\n")
    pieces = re.split(r"(?<!\d)\.(?!\d)", text.strip("."))
    pieces = [item for item in pieces if not set(item).issubset(OFFICIAL_EMPTY_SEGMENT_PUNCTUATION)]
    return "\n".join(pieces)


def _official_cut5(text: str) -> str:
    text = text.strip("\n")
    merged_items: list[str] = []
    chars: list[str] = []

    for index, char in enumerate(text):
        if char in OFFICIAL_CUT5_PUNCTUATION:
            is_decimal_dot = is_decimal_dot_at(text, index)
            if is_decimal_dot:
                chars.append(char)
            else:
                chars.append(char)
                merged_items.append("".join(chars))
                chars = []
            continue
        chars.append(char)

    if chars:
        merged_items.append("".join(chars))

    result = [item for item in merged_items if not set(item).issubset(OFFICIAL_CUT5_PUNCTUATION)]
    return "\n".join(result)


OFFICIAL_SPLIT_METHODS = {
    "cut0": _official_cut0,
    "cut1": _official_cut1,
    "cut2": _official_cut2,
    "cut3": _official_cut3,
    "cut4": _official_cut4,
    "cut5": _official_cut5,
}


def _official_process_text_lines(lines: list[str]) -> list[str]:
    if all(item in [None, " ", "\n", ""] for item in lines):
        raise ValueError("请输入有效文本")
    filtered = [item for item in lines if item not in [None, " ", ""]]
    return _merge_leading_closer_segments(filtered)


def _consume_following_closer_characters(text: str, start_index: int) -> int:
    cursor = start_index
    while cursor < len(text):
        while cursor < len(text) and text[cursor].isspace() and text[cursor] != "\n":
            cursor += 1
        if cursor < len(text) and text[cursor] in _SEGMENT_CLOSER_CHARACTERS:
            cursor += 1
            continue
        break
    return cursor


def _split_leading_closer_prefix(text: str) -> tuple[str, str]:
    cursor = 0
    while cursor < len(text) and text[cursor] in _SEGMENT_CLOSER_CHARACTERS:
        cursor += 1
    return text[:cursor], text[cursor:]


def _merge_leading_closer_segments(lines: list[str]) -> list[str]:
    merged: list[str] = []
    for item in lines:
        text = item
        if merged:
            closer_prefix, remainder = _split_leading_closer_prefix(text)
            if closer_prefix:
                merged[-1] += closer_prefix
                text = remainder
                if not text:
                    continue
                if text.strip() == "":
                    merged[-1] += text
                    continue
        merged.append(text)
    return merged


def _official_merge_short_text_in_array(lines: list[str], threshold: int) -> list[str]:
    if len(lines) < 2:
        return lines

    result: list[str] = []
    current = ""
    for line in lines:
        current += line
        if len(current) >= threshold:
            result.append(current)
            current = ""

    if current:
        if not result:
            result.append(current)
        else:
            result[-1] += current
    return result


def split_text_segments_official(text: str, text_split_method: str = "cut5") -> list[str]:
    normalized = text.strip("\n")
    if not normalized:
        return []

    splitter = OFFICIAL_SPLIT_METHODS.get(text_split_method)
    if splitter is None:
        raise ValueError(f"Unsupported text_split_method '{text_split_method}'.")

    split_result = splitter(normalized)
    while "\n\n" in split_result:
        split_result = split_result.replace("\n\n", "\n")

    lines = _official_process_text_lines(split_result.split("\n"))
    return _official_merge_short_text_in_array(lines, threshold=5)


def split_text_segments_raw_strong_punctuation(text: str) -> list[str]:
    normalized = text.strip("\n")
    if not normalized:
        return []
    return _official_process_text_lines(_official_split_sentence_units(normalized))


def split_text_segments_zh_period(text: str) -> list[str]:
    normalized = text.strip("\n")
    if not normalized:
        return []

    pieces: list[str] = []
    start = 0
    for index, char in enumerate(normalized):
        if char not in {"。", "."}:
            continue
        if is_decimal_dot_at(normalized, index):
            continue
        end = _consume_following_closer_characters(normalized, index + 1)
        pieces.append(normalized[start:end])
        start = end

    if start < len(normalized):
        pieces.append(normalized[start:])
    return _official_process_text_lines(pieces)


def compute_effective_margin_frame_count(
    *,
    decoder_frame_count: int,
    requested_margin_frame_count: int,
    min_core_frame_count: int = 10,
) -> int:
    if decoder_frame_count <= 0 or requested_margin_frame_count <= 0:
        return 0
    return min(requested_margin_frame_count, max((decoder_frame_count - min_core_frame_count) // 2, 0))


def build_phones_and_bert_features(
    text: str,
    language: str,
    version: str,
    tokenizer,
    bert_model,
    device: str,
    is_half: bool,
    default_lang: str | None = None,
    return_norm_text: bool = False,
):
    import torch

    from GPT_SoVITS.text import cleaned_text_to_sequence
    from GPT_SoVITS.text.LangSegmenter import LangSegmenter
    from GPT_SoVITS.text.cleaner import clean_text

    normalized_text = re.sub(r" {2,}", " ", text)
    textlist: list[str] = []
    langlist: list[str] = []

    if language == "all_zh":
        for item in LangSegmenter.getTexts(normalized_text, "zh"):
            langlist.append(item["lang"])
            textlist.append(item["text"])
    elif language == "all_yue":
        for item in LangSegmenter.getTexts(normalized_text, "zh"):
            if item["lang"] == "zh":
                item["lang"] = "yue"
            langlist.append(item["lang"])
            textlist.append(item["text"])
    elif language == "all_ja":
        for item in LangSegmenter.getTexts(normalized_text, "ja"):
            langlist.append(item["lang"])
            textlist.append(item["text"])
    elif language == "all_ko":
        for item in LangSegmenter.getTexts(normalized_text, "ko"):
            langlist.append(item["lang"])
            textlist.append(item["text"])
    elif language == "en":
        langlist.append("en")
        textlist.append(normalized_text)
    elif language == "auto":
        for item in LangSegmenter.getTexts(normalized_text, default_lang=default_lang):
            langlist.append(item["lang"])
            textlist.append(item["text"])
    elif language == "auto_yue":
        for item in LangSegmenter.getTexts(normalized_text, default_lang=default_lang):
            if item["lang"] == "zh":
                item["lang"] = "yue"
            langlist.append(item["lang"])
            textlist.append(item["text"])
    else:
        for item in LangSegmenter.getTexts(normalized_text):
            if langlist:
                same_lang_group = (item["lang"] == "en" and langlist[-1] == "en") or (
                    item["lang"] != "en" and langlist[-1] != "en"
                )
                if same_lang_group:
                    textlist[-1] += item["text"]
                    continue
            if item["lang"] == "en":
                langlist.append(item["lang"])
            else:
                langlist.append(language.replace("all_", ""))
            textlist.append(item["text"])

    phones_list: list[list[int]] = []
    bert_list: list[torch.Tensor] = []
    norm_text_list: list[str] = []
    target_dtype = torch.float16 if is_half else torch.float32

    for index, current_text in enumerate(textlist):
        lang = langlist[index]
        phones, word2ph, norm_text = clean_text(current_text, lang, version)
        phones = cleaned_text_to_sequence(phones, version)
        norm_text_list.append(norm_text)

        if lang in ["zh", "yue"]:
            with torch.no_grad():
                inputs = tokenizer(norm_text, return_tensors="pt")
                for key in inputs:
                    inputs[key] = inputs[key].to(device)
                result = bert_model(**inputs, output_hidden_states=True)
                hidden = torch.cat(result["hidden_states"][-3:-2], -1)[0].cpu()[1:-1]
            phone_level_feature = []
            for word_index in range(len(word2ph)):
                phone_level_feature.append(hidden[word_index].repeat(word2ph[word_index], 1))
            bert = torch.cat(phone_level_feature, dim=0).T
        else:
            bert = torch.zeros((1024, len(phones)), dtype=target_dtype)

        phones_list.append(phones)
        bert_list.append(bert)

    bert = torch.cat(bert_list, dim=1).to(target_dtype)
    phones = sum(phones_list, [])
    if return_norm_text:
        return phones, bert, "".join(norm_text_list)
    return phones, bert
