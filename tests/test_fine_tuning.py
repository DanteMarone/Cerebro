import json
import csv
from fine_tuning import validate_dataset_path, convert_dataset_format, preview_dataset_samples


def test_validate_dataset_path(tmp_path):
    json_file = tmp_path / "data.json"
    json_file.write_text("[]")
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("prompt,completion\n")
    assert validate_dataset_path(str(json_file))
    assert validate_dataset_path(str(csv_file))
    assert not validate_dataset_path(str(tmp_path / "missing.json"))
    assert not validate_dataset_path(str(tmp_path / "file.txt"))


def test_convert_dataset_format_json(tmp_path):
    data = [
        {"prompt": "hi", "completion": "hello"},
        {"prompt": "bye", "completion": "goodbye"},
    ]
    json_file = tmp_path / "d.json"
    json_file.write_text(json.dumps(data))
    result = convert_dataset_format(str(json_file))
    assert result == data


def test_convert_dataset_format_csv(tmp_path):
    csv_file = tmp_path / "d.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["prompt", "completion"])
        writer.writeheader()
        writer.writerow({"prompt": "a", "completion": "b"})
    result = convert_dataset_format(str(csv_file))
    assert result == [{"prompt": "a", "completion": "b"}]


def test_preview_dataset_samples(tmp_path):
    data = [
        {"prompt": "p1", "completion": "c1"},
        {"prompt": "p2", "completion": "c2"},
        {"prompt": "p3", "completion": "c3"},
    ]
    json_file = tmp_path / "d.json"
    json_file.write_text(json.dumps(data))
    preview = preview_dataset_samples(str(json_file), num_samples=2)
    assert preview == data[:2]
