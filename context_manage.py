#file = open('data.txt', 'w')
#file.write('hello5')

#with open('data.txt', 'w') as file:
#    file.write('hello5')

class CountextExample:
    def __init__(self):
        print('Call __init__():')
        self.x = 42

    def __enter__(self):
        print('Call __enter__):')

    def __exit__(self, exc_type, exc_val, exc_tb):
        print('Call __exit__():')
        print(exc_type)
        print(ext_val)
        print(ext_tb)
        print('******')

cm = CountextExample()

with cm as c:
    print(c.x)
print('After with')

@contextmanager
def open_file(filename. mode):
    f = open(filename, mode)
    try:
        yield f
    finally:
        f.close()

with open_file('data.txt, w') as file:
    file.write('hello6')
    raise Exception('Something went wrong')
