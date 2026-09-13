export function pageQuery(page:number, limit:number, filters:Record<string,string> = {}):string {
  const safePage = Number.isInteger(page) && page >= 1 ? page : 1;
  const safeLimit = Number.isInteger(limit) && limit >= 1 && limit <= 200 ? limit : 50;
  const qs = new URLSearchParams({page:String(safePage),limit:String(safeLimit)});
  for (const [key,value] of Object.entries(filters)) if (value) qs.set(key,value);
  return qs.toString();
}
