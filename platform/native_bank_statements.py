"""Independent formatter for the deployed bank-simulator statement protocol."""
from decimal import Decimal


def statement_text(statement,account,logs):
    date=statement['account_statement_date'];currency=account['account_currency']
    opening=Decimal(str(account['book_balance']))+sum((Decimal(str(row['transaction_amount'])) if row['debit_credit']=='DEBIT' else -Decimal(str(row['transaction_amount']))) for row in logs)
    def balance(amount):return ('C' if amount>=0 else 'D')+date.strftime('%y%m%d')+currency+f'{abs(amount):.2f}'.replace('.',',')
    result=[':20:'+str(statement['id']),':25:'+account['account_number'],':28C:1/1',':60F:'+balance(opening)]
    for row in logs:
        debit=row['debit_credit']=='DEBIT';amount=row['transaction_amount'];direction=('R' if amount<0 else '')+('D' if debit else 'C');at=row['transaction_date']
        money=f'{Decimal(abs(amount)):015.2f}'.replace('.',',')
        result.append(':61:'+at.strftime('%y%m%d%m%d')+direction+money+'NTRF'+row['customer_reference_no']+'//'+row['reference_no'])
        result.append(':86:'+'\n'.join(str(row.get('narrative_'+str(i))) for i in range(1,7)))
    result.append(':62F:'+balance(Decimal(account['book_balance'])))
    return '\n'.join(result)
