# demo

- `labels/`: two **fictional** labels (`DEMO LABEL - NOT A REAL PRODUCT`), written like real ones. `scripts/demo.py` turns them into PDFs.
- `replies/`: Qwen3.6's own replies to those labels and to the real Captan 80 DF label, saved with `scripts/read_label.py --save-reply` on the GB10. Tests and the demo use them as the fake model.
- `real-labels.tsv`: real, public labels from EPA's [Pesticide Product Label System](https://www.epa.gov/pesticide-labels), with their SHA-256. `scripts/fetch_labels.sh` downloads them; they never go in git.

The Captan label is the 2011 accepted label for EPA Reg. No. 42750-231. It's a real label used as demo data, not a current one: a farm uses the label on its own container.
