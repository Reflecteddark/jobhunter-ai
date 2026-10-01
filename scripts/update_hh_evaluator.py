import json
import sqlite3
import os

repo_dir = r"C:\Users\strel\.gemini\antigravity\scratch\jobhunter-ai"
wf_path = os.path.join(repo_dir, "workflows", "hh_jobhunter_workflow.json")
db_path = r"C:\Users\strel\.n8n\database.sqlite"

new_evaluator_code = """// Code - Fast Evaluator & Pitch Generator (HeadHunter)
const hhData = $input.item.json;

// 0. Константы курсов валют
const CURRENCY_RATES = {
  RUB: 1,
  RUR: 1,
  USD: 92,
  EUR: 100,
  KZT: 0.19,
  BYN: 28,
  BYR: 28
};

// 1. Защита от ошибок HTTP / отсутствия данных
if (!hhData || hhData.error || !hhData.id) {
  return {
    json: {
      id: (hhData && hhData.id) || 'error',
      alternate_url: '',
      name: 'Ошибка загрузки вакансии',
      employer: { name: 'Неизвестно' },
      salary: null,
      is_relevant: false,
      reject_reason: 'Ошибка API / Вакансия недоступна',
      pitch: ''
    }
  };
}

// 2. Проверка архивности (булево или строка)
if (hhData.archived === true || hhData.archived === 'true') {
  return {
    json: {
      ...hhData,
      is_relevant: false,
      reject_reason: 'Вакансия в архиве',
      pitch: ''
    }
  };
}

const name = String(hhData.name || '');
const emp = String(hhData.employer?.name || '');
const rawDesc = String(hhData.description || '').replace(/<[^>]*>?/gm, ' ').replace(/\\s+/g, ' ').trim();
const fullText = (name + ' ' + emp + ' ' + rawDesc).toLowerCase();

// === Регулярные выражения фильтров ===
const engRegex = /(анг[л-я]\\s+яз|анг[л-я]\\s+яп|анг[л-я]{2,4}\\s+b[12]|анг[л-я]{2,4}\\s+c[12]|анг[л-я]{2,4}\\s+int|анг[л-я]{2,4}\\s+adv|анг[л-я]*\\s+свободн|english\\s+(level|required|b1|b2|c1|c2|fluent|advanced|intermediate)|\\b(level\\s+)?(b2|c1|c2)\\b(?!\\s*b|\\w)|upper[- ]intermediate|\\badvanced\\s+english\\b|\\bfluent\\s+english\\b)/i;
const edtechRegex = /(онлайн[- ]?школ|edtech|skyeng|фоксфорд|tetrica|нетологи|skillbox|geekbrains|синерги|лайк\\s*центр|like\\s*центр|interneturok|maximum\\s+education|курс[а-я]*\\s+(английск|программир|дет|школьн|егэ|огэ|массаж|ai|it)|обучен[а-я]*\\s+детей\\s+(английск|программир|шахмат|ai|it|робототехник)|вебинар[а-я]*\\s+продаж|авто[- ]?вебинар|марафон[а-я]*\\s+продаж|интенсив|инфобиз|наставничеств|коучинг)/i;
const cryptoRegex = /(криптовалют|криптобирж|crypto|web3|блокчейн|p2p\\s+арбитраж|гемблинг|беттинг|казино)/i;
const badRolesRegex = /(стажер|junior|ассистент|помощник|холодн[а-я]*\\s+обзвон|оператор\\s+колл[- ]?центра|оператор\\s+на\\s+телефоне)/i;

// 3. Проверка английского языка
const langs = Array.isArray(hhData.languages) ? hhData.languages : [];
const hasEng = langs.some(l => l.id === 'eng' || (l.name && l.name.toLowerCase().includes('англ')));
if (hasEng || engRegex.test(fullText)) {
  return { json: { ...hhData, is_relevant: false, reject_reason: "Требуется знание английского языка", pitch: "" } };
}

// 4. Проверка онлайн-школ и EdTech
if (edtechRegex.test(fullText)) {
  return { json: { ...hhData, is_relevant: false, reject_reason: "Онлайн-школа / EdTech / Инфобиз", pitch: "" } };
}

// 5. Проверка крипты и гемблинга
if (cryptoRegex.test(fullText)) {
  return { json: { ...hhData, is_relevant: false, reject_reason: "Крипта / трейдинг / Web3 / гемблинг", pitch: "" } };
}

// 6. Проверка нецелевых ролей (стажеры, ассистенты, колл-центр по названию)
if (badRolesRegex.test(name.toLowerCase())) {
  return { json: { ...hhData, is_relevant: false, reject_reason: "Нецелевая роль (стажер / ассистент / колл-центр)", pitch: "" } };
}

// 7. Проверка формата (строго удаленка)
const isExplicitRemote = (hhData.schedule && hhData.schedule.id === 'remote') ||
  (Array.isArray(hhData.work_format) && hhData.work_format.some(wf => wf.id === 'remote' || wf.name?.toLowerCase().includes('удален'))) ||
  /100%\\s*удален|полная\\s+удален|только\\s+удален|удаленный\\s+формат|дистанционный\\s+формат/i.test(fullText);
const isExplicitOffice = /(только\\s+в\\s+офис|работа\\s+в\\s+офисе|офисный\\s+формат|на\\s+территории\\s+работодателя|гибридный\\s+формат|испытательный\\s+срок\\s+в\\s+офисе)/i.test(fullText);

if (isExplicitOffice || !isExplicitRemote) {
  return { json: { ...hhData, is_relevant: false, reject_reason: "Не удаленка / офис / гибрид", pitch: "" } };
}

// 8. Проверка зарплаты (только для HH: строго от 100 000 ₽, если зарплата указана)
if (hhData.salary) {
  const curr = (hhData.salary.currency || 'RUR').toUpperCase();
  const rate = CURRENCY_RATES[curr] || 1;
  const toSal = hhData.salary.to;
  const fromSal = hhData.salary.from;

  const effectiveFrom = (fromSal !== null && fromSal !== undefined) ? fromSal * rate : null;
  const effectiveTo = (toSal !== null && toSal !== undefined) ? toSal * rate : null;

  // Если указана нижняя планка - она должна быть строго от 100 000 ₽
  if (effectiveFrom !== null && effectiveFrom < 100000) {
    return {
      json: {
        ...hhData,
        is_relevant: false,
        reject_reason: `Зарплата от ${fromSal} ${curr} (ниже 100 000 ₽)`,
        pitch: ""
      }
    };
  }

  // Если указан только потолок "до ..." без нижней границы "от ..."
  if (effectiveFrom === null && effectiveTo !== null) {
    return {
      json: {
        ...hhData,
        is_relevant: false,
        reject_reason: `Указан только потолок до ${toSal} ${curr} (нет оклада от 100 000 ₽)`,
        pitch: ""
      }
    };
  }
}

if (/только\\s+процент|без\\s+оклада|оплата\\s+за\\s+результат\\s+без\\s+оклада/i.test(fullText)) {
  return { json: { ...hhData, is_relevant: false, reject_reason: "Нет оклада / только процент", pitch: "" } };
}

// Проверка явного низкого оклада в тексте описания (если в тексте явно указан фикс ниже 100к)
const lowFixMatch = rawDesc.match(/(?:оклад|фикс|фиксированная\\s+часть|базовая\\s+ставка|ставка)\\s*(?:на\\s+испытательный\\s+срок|на\\s+руки|до\\s+вычета)?\\s*(?:составляет|:|-|\\s|от)?\\s*([1-9]\\d?)\\s*(?:000|тыс|т\\.р|тр|к)(?![а-яё\\w])/i);
if (lowFixMatch) {
  const amount = parseInt(lowFixMatch[1], 10);
  if (amount < 100) {
    return {
      json: {
        ...hhData,
        is_relevant: false,
        reject_reason: `Низкий оклад в описании (${amount} 000 ₽, ниже 100 000 ₽)`,
        pitch: ""
      }
    };
  }
}

// 9. График работы (не сменный)
if (/график\\s+(2\\/2|3\\/3|1\\/3|сменный|по\\s+сменам|ночные)/i.test(fullText)) {
  return { json: { ...hhData, is_relevant: false, reject_reason: "График работы не 5/2", pitch: "" } };
}

// === ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ -> ВАКАНСИЯ ПОДХОДИТ! ===
const salStr = hhData.salary
  ? ((hhData.salary.from ? 'от ' + hhData.salary.from : '') + (hhData.salary.to ? ' до ' + hhData.salary.to : '') + ' ' + (hhData.salary.currency || 'RUR'))
  : 'по договоренности';

// Извлечение обязанностей для емкого Pitch
let tasks = '';
const taskMatch = rawDesc.match(/(?:обязанности|задачи|предстоит|чем\\s+предстоит\\s+заниматься)[:\\s]+([^.!?\\n]{20,180})/i);
if (taskMatch) {
  tasks = taskMatch[1].trim();
} else {
  tasks = rawDesc.slice(0, 120).trim() + '...';
}

const pitch = `🏢 Бизнес: ${emp || 'B2B'} | 💰 Доход: ${salStr} | 🎯 Задачи: ${tasks}`;

return {
  json: {
    ...hhData,
    is_relevant: true,
    reject_reason: null,
    pitch: pitch
  }
};"""

# 1. Update workflows/hh_jobhunter_workflow.json
with open(wf_path, "r", encoding="utf-8") as f:
    wf = json.load(f)

updated_file = False
for node in wf.get("nodes", []):
    if node.get("name") == "Code - Fast Evaluator":
        node["parameters"]["jsCode"] = new_evaluator_code
        updated_file = True
        break

if updated_file:
    with open(wf_path, "w", encoding="utf-8") as f:
        json.dump(wf, f, indent=2, ensure_ascii=False)
    print(f"Successfully updated {wf_path}")
else:
    print(f"Node 'Code - Fast Evaluator' not found in {wf_path}")

# 2. Update SQLite database workflow_entity
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute("SELECT nodes FROM workflow_entity WHERE id = 'PMmCjg4AL0rXpVqO'")
row = cur.fetchone()
if row:
    nodes = json.loads(row[0])
    updated_db = False
    for node in nodes:
        if node.get("name") == "Code - Fast Evaluator":
            node["parameters"]["jsCode"] = new_evaluator_code
            updated_db = True
            break
    if updated_db:
        cur.execute("UPDATE workflow_entity SET nodes = ? WHERE id = 'PMmCjg4AL0rXpVqO'", (json.dumps(nodes, ensure_ascii=False),))
        conn.commit()
        print("Successfully updated workflow_entity PMmCjg4AL0rXpVqO in database.sqlite")
    else:
        print("Node 'Code - Fast Evaluator' not found in database nodes")
else:
    print("Workflow PMmCjg4AL0rXpVqO not found in database.sqlite")

conn.close()
