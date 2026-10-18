// SPDX-License-Identifier: MIT
pragma solidity 0.8.26;
// RESEARCH HARNESS ONLY. Installed with anvil_setCode; never deploy to mainnet.
interface Token {function balanceOf(address) external view returns(uint);function approve(address,uint) external returns(bool);}
interface Provider {function getPool() external view returns(address);}
interface Pool {function flashLoanSimple(address,address,uint,bytes calldata,uint16) external;}
interface V2 {function swapExactTokensForTokens(uint,uint,address[] calldata,address,uint) external returns(uint[] memory);}
interface V3 {
 struct Params {address tokenIn;address tokenOut;uint24 fee;address recipient;uint deadline;uint amountIn;uint amountOutMinimum;uint160 sqrtPriceLimitX96;}
 function exactInputSingle(Params calldata) external payable returns(uint);
}
contract Replay {
 address constant USDC=0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48;
 address constant WETH=0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2;
 address constant PROVIDER=0x2f39d218133AFaB8F2B819B1066c7E434Ad94E9e;
 address constant U2=0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D;
 address constant S2=0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F;
 address constant U3=0xE592427A0AEce92De3Edee1F18E0157C05861564;
 bool active;
 event Outcome(uint profit);
 function run(uint amount,uint8 first,uint8 second,bool flash,uint minProfit) external payable returns(uint profit) {
  require(block.chainid==31337,"LOCAL FORK ONLY");require(!active && first!=second,"route");active=true;
  uint beforeBalance=Token(USDC).balanceOf(address(this));
  if(flash) Pool(Provider(PROVIDER).getPool()).flashLoanSimple(address(this),USDC,amount,abi.encode(first,second),0);
  else {require(beforeBalance>=amount,"capital");trade(amount,first,second);}
  uint afterBalance=Token(USDC).balanceOf(address(this));
  require(afterBalance>=beforeBalance+minProfit,"minProfit");profit=afterBalance-beforeBalance;active=false;
  (bool paid,)=block.coinbase.call{value:msg.value}("");require(paid,"builder payment");emit Outcome(profit);
 }
 function executeOperation(address asset,uint amount,uint premium,address initiator,bytes calldata params) external returns(bool) {
  require(active && msg.sender==Provider(PROVIDER).getPool() && initiator==address(this) && asset==USDC,"callback");
  (uint8 first,uint8 second)=abi.decode(params,(uint8,uint8));trade(amount,first,second);
  require(Token(USDC).approve(msg.sender,amount+premium),"approve repayment");return true;
 }
 function trade(uint amount,uint8 first,uint8 second) internal {uint out=swap(USDC,WETH,amount,first);swap(WETH,USDC,out,second);}
 function swap(address a,address b,uint amount,uint8 v) internal returns(uint out) {
  require(v<4,"venue");address router=v==0?U2:v==1?S2:U3;
  require(Token(a).approve(router,0) && Token(a).approve(router,amount),"approve");
  if(v<2){address[] memory path=new address[](2);path[0]=a;path[1]=b;uint[] memory amounts=V2(router).swapExactTokensForTokens(amount,0,path,address(this),block.timestamp);out=amounts[1];}
  else out=V3(router).exactInputSingle(V3.Params(a,b,v==2?500:3000,address(this),block.timestamp,amount,0,0));
 }
}
