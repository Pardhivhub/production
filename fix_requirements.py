with open('requirements.txt', 'r') as f:
    lines = f.readlines()

with open('requirements.txt', 'w') as f:
    for line in lines:
        if "rank_bm25" in line:
            f.write("rank_bm25\n")
        else:
            f.write(line)
