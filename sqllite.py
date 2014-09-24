
import sqlite3

if __name__=="__main__":
	conn = sqlite3.connect('example.db')
	
	c = conn.cursor()
	
	# Create table
	c.execute('''CREATE TABLE stocks (date text, trans text, symbol text, qty real, price real)''')
	
	# Insert a row of data
	c.execute("INSERT INTO stocks VALUES ('2006-01-05','BUY','RHAT',100,35.14)")
	# Save (commit) the changes
	conn.commit()
	conn.close()

	## Second session
	t = ('RHAT',)
	c.execute('SELECT * FROM stocks WHERE symbol=?', t)
	print c.fetchone()