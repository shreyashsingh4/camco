const API_KEY = 'devkey';

export async function apiGet(path) {
  const res = await fetch(path, {
    headers: { 'X-API-Key': API_KEY }
  });
  if (!res.ok) throw new Error(`GET ${path} ${res.status}`);
  return res.json();
}

export async function apiPost(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-API-Key': API_KEY },
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new Error(`POST ${path} ${res.status}`);
  return res.json();
}
