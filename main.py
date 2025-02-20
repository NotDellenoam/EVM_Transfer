import asyncio
from decimal import Decimal

from client import Client


async def main():
    private_key = input("Enter private key: ")

    proxy = input("Enter proxy or leave empty: ")
    if not proxy:
        proxy = None

    contract_address = input(
        "Enter contract address or leave empty to use native token: "
    )
    if not contract_address:
        contract_address = None

    web3_client = Client(private_key=private_key, proxy=proxy)

    if contract_address:
        await web3_client.set_contract(contract_address)

    recipient = input("Enter recipient address: ")
    amount_to_transfer = Decimal(input("Enter amount to transfer: "))

    transcation = await web3_client.prepare_transaction(recipient, amount_to_transfer)
    tx_hash = await web3_client.sign_and_send_transaction(transcation)
    tx_receipt = await web3_client.wait_for_transaction(tx_hash)

    if tx_receipt["status"] == 1:
        print("Transaction succeeded")
    else:
        print("Transaction failed")


if __name__ == "__main__":
    asyncio.run(main())
