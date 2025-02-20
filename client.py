import json
from decimal import Decimal

import aiofiles
from eth_typing import HexStr
from loguru import logger
from web3 import AsyncWeb3
from web3.contract.async_contract import AsyncContract
from web3.exceptions import ContractLogicError, InvalidTransaction, TimeExhausted
from web3.types import TxParams, Wei

import config


class Client:
    BASE_EXPLORER_URL = config.BASE_EXPLORER_URL
    RPC_URL = config.RPC_URL
    USE_EIP_1559 = config.USE_EIP_1559

    def __init__(
        self,
        private_key: str,
        proxy: str | None = None,
    ) -> None:
        request_kwargs = {"proxy": proxy} if proxy else {}
        self.web3 = AsyncWeb3(
            AsyncWeb3.AsyncHTTPProvider(self.RPC_URL, request_kwargs=request_kwargs)
        )

        self.private_key = private_key
        self.address = self.web3.eth.account.from_key(private_key).address

        self.contract: AsyncContract | None = None
        self.contract_address: str | None = None

    async def set_contract(self, contract_address: str):
        abi = await self._load_abi()
        self.contract_address = self.web3.to_checksum_address(contract_address)
        self.contract = self.web3.eth.contract(address=self.contract_address, abi=abi)

    def to_wei(self, value: int | Decimal, decimals: int) -> Wei:
        unit_names = {
            6: "mwei",
            9: "gwei",
            18: "ether",
        }

        unit_name = unit_names.get(decimals)

        if not unit_name:
            logger.error(f"Can't find unit name with decimals: {decimals}")
            raise ValueError(f"Can't find unit name with decimals: {decimals}")

        return self.web3.to_wei(value, unit_name)

    def from_wei(self, value: int, decimals: int) -> int | Decimal:
        unit_names = {
            6: "mwei",
            9: "gwei",
            18: "ether",
        }

        unit_name = unit_names.get(decimals)

        if not unit_name:
            logger.error(f"Can't find unit name with decimals: {decimals}")
            raise ValueError(f"Can't find unit name with decimals: {decimals}")

        return self.web3.from_wei(value, unit_name)

    async def prepare_transaction(
        self, recipient: str, value: int | Decimal
    ) -> TxParams:
        recipient = self.web3.to_checksum_address(recipient)

        transaction: TxParams = {
            "chainId": await self.web3.eth.chain_id,
            "nonce": await self.web3.eth.get_transaction_count(self.address),
            "from": self.address,
        }

        if not self.contract:
            transaction["value"] = self.web3.to_wei(value, "ether")

        if self.USE_EIP_1559:
            base_fee = await self.web3.eth.gas_price
            max_priority_fee = await self.web3.eth.max_priority_fee
            max_fee = Wei(int((base_fee + max_priority_fee) * 1.05))

            transaction.update(
                {
                    "maxPriorityFeePerGas": Wei(max_priority_fee),
                    "maxFeePerGas": max_fee,
                }
            )

            gas_cost_multiplier = max_fee
        else:
            gas_price = Wei(int((await self.web3.eth.gas_price) * 1.05))
            transaction["gasPrice"] = gas_price

            gas_cost_multiplier = gas_price

        if self.contract:
            try:
                transaction = await self.contract.functions.transfer(
                    recipient,
                    self.to_wei(value, await self.contract.functions.decimals().call()),
                ).build_transaction(transaction)
            except ContractLogicError as error:
                logger.error(f"Transaction failed: {error}")
                raise

        gas_limit = await self.web3.eth.estimate_gas(transaction)
        transaction["gas"] = gas_limit

        gas_cost = self.web3.from_wei(gas_limit * gas_cost_multiplier, "ether")

        if not await self._ensure_sufficient_funds(value, gas_cost):
            logger.error("Insufficient funds")
            raise

        return transaction

    async def sign_and_send_transaction(self, transaction: TxParams):
        try:
            signed_transaction = self.web3.eth.account.sign_transaction(
                transaction, self.private_key
            ).rawTransaction
            print("Transaction signed")

            tx_hash_bytes = await self.web3.eth.send_raw_transaction(signed_transaction)
            tx_hash = self.web3.to_hex(tx_hash_bytes)
            print(f"Transaction on Explorer: {self.BASE_EXPLORER_URL}/tx/{tx_hash}")

            return tx_hash
        except InvalidTransaction as error:
            logger.error(f"Transaction failed: {error}")
            raise

    async def wait_for_transaction(self, tx_hash: HexStr):
        try:
            tx_receipt = await self.web3.eth.wait_for_transaction_receipt(tx_hash)

            return tx_receipt
        except TimeExhausted:
            logger.error("Transaction failed to be mined in 120 seconds")
            raise

    async def _ensure_sufficient_funds(
        self, value: int | Decimal, gas_cost: int | Decimal
    ) -> bool:
        native_balance_wei = await self.web3.eth.get_balance(self.address)
        native_balance = self.web3.from_wei(native_balance_wei, "ether")

        print(f"Native balance: {native_balance}")

        if native_balance < gas_cost:
            logger.error(f"Insufficient balance to cover gas cost: {gas_cost}")
            raise

        if self.contract:
            contract_balance_wei = await self.contract.functions.balanceOf(
                self.address
            ).call()
            decimals = await self.contract.functions.decimals().call()
            contract_balance = self.from_wei(contract_balance_wei, decimals)
            print(f"Contract balance: {contract_balance}")

            if contract_balance < value:
                logger.error(f"Insufficient contract balance: {contract_balance}")
                raise
        else:
            if native_balance < value + gas_cost:
                logger.error(
                    f"Insufficient balance to cover gas cost and transfer amount: {value}"
                )
                raise

        return True

    async def _load_abi(self, path: str = "ERC20_ABI.json"):
        async with aiofiles.open(path) as file:
            abi = json.loads(await file.read())

        return abi
