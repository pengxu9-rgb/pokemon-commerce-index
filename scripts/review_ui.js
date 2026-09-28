const $ = (id) => document.getElementById(id);
let current = null;
let currentMode = "review";
let reviewer = "";

async function request(path, options) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}

async function refreshStatus() {
  const s = await request("/api/status");
  $("status").textContent = `${s.items} 条样本 · ${s.reviewed_once} 条已有首审 · ${s.reviewed_twice} 条双人完成 · ${s.conflicts} 条分歧 · ${s.ready_for_gold} 条可导出`;
}

function showMessage(message) { $("message").textContent = message; }

function renderItem(item, progress, reviews = []) {
  current = item;
  $("workspace").hidden = false;
  $("item-key").textContent = `${item.source.toUpperCase()} · ${item.native_id}`;
  $("review-progress").textContent = progress;
  $("title").textContent = item.title || "（无标题）";
  $("listing-link").href = item.url;
  $("description").textContent = item.description || "测试记录中没有描述。";
  $("images").replaceChildren();
  $("load-images").disabled = !item.image_urls.length;
  $("photo-note").textContent = item.image_urls.length
    ? `记录中有 ${item.image_urls.length} 个图片链接。只在点击后加载；如已失效，请在原 listing 核实，无法查看时保持版本未知。`
    : "记录中没有图片链接。只有找到获准使用的实物图后才能确认版本。";
  $("label-form").reset();
  $("prior-reviews").hidden = !reviews.length;
  $("reason-wrap").hidden = currentMode !== "adjudicate";
  $("form-heading").textContent = currentMode === "adjudicate" ? "填写最终裁决" : "填写独立判断";
  $("submit").textContent = currentMode === "adjudicate" ? "提交裁决并看下一条" : "提交并查看下一条";
  const comparison = $("review-comparison");
  comparison.replaceChildren();
  for (const review of reviews) {
    const block = document.createElement("pre");
    const l = review.label;
    block.textContent = `${review.reviewer}\n单卡: ${l.single_card}\n语言: ${l.language}\n卡组: ${l.set_code || "未知"}\n卡号: ${l.number || "未知"}\n版本: ${l.variant}\n评级: ${l.grade_status || "unknown"} ${l.grade_company || ""} ${l.grade_value || ""}\n看过卡面: ${l.image_seen ? "是" : "否"}\n证据: ${l.evidence_notes || "未填写"}`;
    comparison.append(block);
  }
}

async function loadNext() {
  try {
    const path = currentMode === "adjudicate"
      ? `/api/conflict?reviewer=${encodeURIComponent(reviewer)}`
      : `/api/next?reviewer=${encodeURIComponent(reviewer)}`;
    const data = await request(path);
    if (!data.item) {
      current = null;
      $("workspace").hidden = true;
      showMessage(currentMode === "adjudicate" ? "目前没有待裁决的分歧。" : "该审核员目前没有待审样本。");
      return;
    }
    showMessage("");
    const progress = currentMode === "adjudicate" ? "待裁决分歧" : `该审核员已提交 ${data.reviewer_done} / ${data.total}`;
    renderItem(data.item, progress, data.reviews || []);
  } catch (error) { showMessage(error.message); }
}

$("start").addEventListener("click", async () => {
  reviewer = $("reviewer").value.trim();
  if (!/^[A-Za-z0-9_-]{2,40}$/.test(reviewer)) {
    showMessage("审核员 ID 只能是 2–40 位字母、数字、_ 或 -。");
    return;
  }
  currentMode = $("mode").value;
  await loadNext();
});

$("load-images").addEventListener("click", () => {
  if (!current) return;
  const gallery = $("images");
  gallery.replaceChildren();
  for (const [index, url] of current.image_urls.entries()) {
    const figure = document.createElement("figure");
    const img = document.createElement("img");
    const caption = document.createElement("figcaption");
    img.alt = `商品图片 ${index + 1}`;
    img.referrerPolicy = "no-referrer";
    img.loading = "lazy";
    img.addEventListener("error", () => { caption.textContent = `图片 ${index + 1} 无法加载`; });
    img.src = url;
    caption.textContent = `图片 ${index + 1}`;
    figure.append(img, caption);
    gallery.append(figure);
  }
});

$("label-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!current) return;
  const form = new FormData(event.currentTarget);
  const label = {
    single_card: form.get("single_card"), language: form.get("language"),
    set_code: String(form.get("set_code") || "").trim(),
    number: String(form.get("number") || "").trim(),
    variant: String(form.get("variant") || "unknown").trim().toLowerCase(),
    grade_status: form.get("grade_status"),
    grade_company: form.get("grade_company"),
    grade_value: String(form.get("grade_value") || "").trim(),
    image_seen: form.get("image_seen") === "on",
    evidence_notes: String(form.get("evidence_notes") || "").trim(),
  };
  if ((label.variant !== "unknown" || label.grade_status !== "unknown") && !label.image_seen) {
    showMessage("填写具体版本或评级状态前，需要实际看过可判定的商品图片。");
    return;
  }
  const payload = { reviewer, item_key: current.item_key, label };
  if (currentMode === "adjudicate") payload.reason = String(form.get("reason") || "").trim();
  $("submit").disabled = true;
  try {
    await request(currentMode === "adjudicate" ? "/api/adjudicate" : "/api/review", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
    });
    await refreshStatus();
    await loadNext();
  } catch (error) { showMessage(error.message); }
  finally { $("submit").disabled = false; }
});

refreshStatus().catch((error) => showMessage(error.message));
