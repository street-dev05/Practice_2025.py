def print_message(message):
    print(f'message was: {message}')

print_message('Hello world')

f = print_message

#print(print_message.__call__('Hello world2'))

f('Hello2')

def decorated(function):
    def decorator(function):
        def wrapper(*args, **kwargs):
            print(f'[{datetime.datetime.now()}]call of function: {function.__name__}')
            function(*args, **kwargs)
            print('after call of function:')
            wrapper.label = label
        return wrapper
    return decorator

#decorated_print = decorated(print_message)
#decorated_print('hello3')

@decorated(label='print_function')
def print_message2(message):
    print(f'message was: {message}')

#print_message2 = decorated(print_message)

print_message2('hello4')

print(print__message2.label)



@route('/api/v2', method='POST')
def http_handler(request):
