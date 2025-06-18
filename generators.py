def my_new_generator(max_number: int):
    current = 0
    while(current < max_number):
        yield current
        current += 1

i1 = my_new_generator(10)
i2 = my_new_generator(10)

print(i1, i2)

for i in i1:
    print(i)

for i in i2:
    print('Something')
    print(i)
