# labels

Reading pesticide labels. Standard library only; PDFs need poppler's `pdftotext`.

| File | What |
| --- | --- |
| `extract.py` | A PDF into pages of lines (`pdftotext -layout`), or a photo into an image for the model |
| `model.py` | The OpenAI-compatible client for Qwen (thinking off, temperature 0) and the fakes for tests |
| `reader.py` | The prompt, the `spraywatch.label/1` reply check, and the quote check that sets `quote_verified` |

The model sees every line as `p3 L42: ...` and must cite the page, line and exact words for each interval. A quote counts as verified only when it is on the cited page within two lines of the cited line and its number is the value. After a prompt change, run `scripts/read_label.py` on the real Captan label and refresh `demo/replies/`.
