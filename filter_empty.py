import sys

def main(): 
    for line in sys.stdin:
        line = line.strip()
        if line:
            print(line)

if __name__ == "__main__":
    sys.exit(main())
