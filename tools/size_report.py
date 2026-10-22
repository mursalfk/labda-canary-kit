# lambda-canary-kit/tools/size_report.py
"""Print each image's size and its five heaviest layers, side by side.

  python tools/size_report.py canary-kit:bloated canary-kit:slim

This is how the article's before/after table gets its numbers: run it, paste it.
"""
import subprocess
import sys

MB = 1024 * 1024


def size_bytes(image):
    out = subprocess.run(["docker", "image", "inspect", image, "--format", "{{.Size}}"],
                         check=True, capture_output=True, text=True).stdout
    return int(out.strip())


def layers(image):
    out = subprocess.run(["docker", "history", image, "--no-trunc", "--format", "{{.Size}}|{{.CreatedBy}}"],
                         check=True, capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        size, _, cmd = line.partition("|")
        rows.append((size, " ".join(cmd.split())[:90]))
    return rows


def main(images):
    if not images:
        print(__doc__)
        return 2
    for image in images:
        print(f"\n{image}: {size_bytes(image) / MB:.1f} MB (uncompressed, as Docker reports it)")
        for size, cmd in layers(image)[:5]:
            print(f"  {size:>10}  {cmd}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
