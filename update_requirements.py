import subprocess

def regenerate_clean_requirements():
    print("🧾 正在生成干净的 requirements.txt ...")
    result = subprocess.run(["pip", "freeze"], capture_output=True, text=True, check=True)
    blacklist = {"pkg-resources", "typing", "distutils", "pip", "setuptools", "wheel"}
    lines = []
    for line in result.stdout.splitlines():
        pkg = line.split("==")[0].lower().strip()
        if pkg not in blacklist:
            lines.append(line)
    with open("requirements.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("✅ requirements.txt 已成功重建且干净！")

if __name__ == "__main__":
    regenerate_clean_requirements()
