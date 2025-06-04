TOOL_METADATA = {
    "name": "file-summarizer",
    "description": "Summarize the contents of a text file or provided text"
}


def run_tool(args):
    """Return a short summary of the given file or text.

    Args:
        args (dict): Should contain 'file_path' pointing to a text file or
            'text' with the text to summarize.
    """
    text = args.get("text", "")
    file_path = args.get("file_path")
    if file_path:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            return f"[file-summarizer Error] Failed to read '{file_path}': {e}"

    if not text:
        return "[file-summarizer Error] No text provided."

    words = text.split()
    summary_words = words[:100]
    summary = " ".join(summary_words)
    if len(words) > 100:
        summary += "..."
    return summary
