import sys

def add_numbers(a, b, *args, **kwargs):
    print('a was: ', a)
    print('b was:', b)
    print('Other args: %r' args)
    print('Other kwargs: ', kwargs)
    return a+b

def main():
    number1 = input('Enter the first number')
    number2 = input('Enter the second number')
    number1 = int(number1)
    number2 = int(number2)
    return add_numbers(number1, number2)
#    print(add_numbers(int(number1), int(number2)))
"""
while(1):
    try:
        result = sys.stdin.read(4)
        print(int(result))
    except Exception as e:
        print('Error: %s' % e.message)
        print(f'Error: {e}')


if __name__ == "__main__":
    sys.exit(main())

#sys.stdout.write('Message for stdout\n')
#sys.stderr.write('Error\n')
#sys.exit(0)
"""
l = [1212, 10, 20]
add_numbers(*l)
d = {
        'a': 1212,
        'b': 12,
        'c': 20
        }
add_numbers(**d)
