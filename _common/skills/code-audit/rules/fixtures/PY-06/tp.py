import logging

def login(u, pw):
    logging.info('user login', extra={'password': pw})
