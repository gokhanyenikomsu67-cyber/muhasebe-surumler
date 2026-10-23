// Muhasebe programının WhatsApp köprüsü. Program (backend/app/bot.py) başlatır; elle çalıştırılmaz.
// Botun ayrı numarasıyla WhatsApp'a bağlanır (ilk açılışta programın ekranında QR çıkar), gelen yazıyı programa
// sorar, program cevap verirse aynı sohbete yazar. Programa yalnız bu bilgisayardan, gizli anahtarla bağlanır.
import makeWASocket, { Browsers, DisconnectReason, fetchLatestBaileysVersion, getContentType, isJidGroup,
  useMultiFileAuthState } from 'baileys'
import pino from 'pino'
import QRCode from 'qrcode'

const ADRES = process.env.MUHASEBE_ADRES || 'http://127.0.0.1:8000'
const ANAHTAR = process.env.MUHASEBE_BOT_ANAHTARI || ''
const OTURUM = process.env.BOT_OTURUM || './oturum'
const log = pino({ level: 'warn' })
const gruplar = new Map() // grup kimliği -> grup adı

let programaUlasilamayan = 0
let sonDurum = 'baglaniyor'

async function programa(yol, govde) {
  const yanit = await fetch(ADRES + '/api/bot/' + yol, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Bot-Anahtari': ANAHTAR },
    body: JSON.stringify(govde)
  })
  if (yanit.status === 401) {
    // Program yeniden açılmış (yeni anahtar) ya da başka bir program: bu köprü kapanır, yenisi başlar
    console.error('Program bu köprüyü tanımıyor, kapanıyor.')
    process.exit(0)
  }
  if (!yanit.ok) throw new Error('Program yanıtı ' + yanit.status)
  return yanit.json()
}

async function durumBildir(durum, ek = {}) {
  try {
    const r = await programa('kopru-durum', { durum, ...ek })
    programaUlasilamayan = 0
    if (r && r.acik === false) process.exit(0)
  } catch (e) {
    console.error('Durum bildirilemedi:', e.message)
  }
}

// Program kapandıysa köprü de kapanır (2 dakika ulaşılamazsa)
setInterval(async () => {
  try {
    await programa('kopru-durum', { durum: sonDurum })
    programaUlasilamayan = 0
  } catch {
    if (++programaUlasilamayan >= 4) process.exit(0)
  }
}, 30_000)

// Mesajın bağlamı (bahsedilenler, yanıtlanan mesajın sahibi)
function baglam(m) {
  const ic = m.message?.ephemeralMessage?.message || m.message
  return ic?.extendedTextMessage?.contextInfo || {}
}

// "905321234567:12@s.whatsapp.net" -> "905321234567"
const kimlikNo = (jid) => (jid || '').split('@')[0].split(':')[0]

function yazi(m) {
  const icerik = m.message
  if (!icerik) return ''
  const tur = getContentType(icerik)
  if (tur === 'conversation') return icerik.conversation || ''
  if (tur === 'extendedTextMessage') return icerik.extendedTextMessage?.text || ''
  if (tur === 'ephemeralMessage') return yazi({ message: icerik.ephemeralMessage.message })
  return ''
}

async function grupAdi(sock, jid) {
  if (gruplar.has(jid)) return gruplar.get(jid)
  try {
    const bilgi = await sock.groupMetadata(jid)
    gruplar.set(jid, bilgi.subject)
    return bilgi.subject
  } catch {
    return null
  }
}

async function baglan() {
  const { state, saveCreds } = await useMultiFileAuthState(OTURUM)
  let version
  try {
    ({ version } = await fetchLatestBaileysVersion())
  } catch { /* paketteki sürüm kullanılır */ }
  const sock = makeWASocket({
    auth: state, logger: log, browser: Browsers.windows('Muhasebe'), markOnlineOnConnect: false,
    syncFullHistory: false, ...(version ? { version } : {})
  })
  sock.ev.on('creds.update', saveCreds)

  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      sonDurum = 'qr'
      await durumBildir('qr', { qr: await QRCode.toDataURL(qr, { margin: 1, width: 280 }) })
    }
    if (connection === 'open') {
      sonDurum = 'bagli'
      await durumBildir('bagli', { numara: sock.user?.id || null })
    } else if (connection === 'close') {
      const kod = lastDisconnect?.error?.output?.statusCode
      if (kod === DisconnectReason.loggedOut) {
        sonDurum = 'cikis'
        await durumBildir('cikis', { hata: 'Telefondan bağlantı kaldırıldı. Yeniden bağlamak için botu açıp QR okutun.' })
        process.exit(0)
      }
      if (kod === DisconnectReason.connectionReplaced) {
        sonDurum = 'hata'
        await durumBildir('hata', { hata: 'Bu numara başka bir yerde açıldı.' })
        process.exit(0)
      }
      sonDurum = 'baglaniyor'
      await durumBildir('baglaniyor')
      setTimeout(baglan, 5000)
    }
  })

  sock.ev.on('messages.upsert', async ({ messages, type }) => {
    if (type !== 'notify') return
    for (const m of messages) {
      try {
        if (!m.message || m.key.fromMe) continue
        const sohbet = m.key.remoteJid
        if (!sohbet || sohbet === 'status@broadcast') continue
        const hamMetin = yazi(m).trim()
        if (!hamMetin || hamMetin.length > 300) continue
        const grup = isJidGroup(sohbet)
        const gonderen = grup ? m.key.participant : sohbet
        let alt = grup ? (m.key.participantAlt || m.key.participantPn) : (m.key.remoteJidAlt || m.key.senderPn)
        if (!gonderen) continue
        // Grupta numara gizliyse (@lid) WhatsApp'ın eşlemesinden numara bulunur
        if (!alt && gonderen.endsWith('@lid')) {
          try { alt = await sock.signalRepository?.lidMapping?.getPNForLID(gonderen) } catch { /* bulunamadı */ }
        }
        // Bota yazıldı mı: grupta @bahsedildi ya da botun mesajına yanıt verildi. Özel sohbette yalnız tanınan soruya
        // cevap verilir (hitap sayılmaz), "anlayamadım" yazılmaz
        const benim = new Set([kimlikNo(sock.user?.id), kimlikNo(sock.user?.lid)].filter(Boolean))
        const b = baglam(m)
        const hitap = grup && ((b.mentionedJid || []).some((j) => benim.has(kimlikNo(j))) || benim.has(kimlikNo(b.participant)))
        const metin = hamMetin.replace(/@\d+/g, ' ').replace(/\s+/g, ' ').trim()
        if (!metin) continue
        const { cevap } = await programa('mesaj', {
          gonderen, gonderen_alt: alt || null, ad: m.pushName || null, metin, hitap,
          grup: grup ? await grupAdi(sock, sohbet) : null
        })
        if (cevap) await sock.sendMessage(sohbet, { text: cevap }, { quoted: m })
      } catch (e) {
        console.error('Mesaj işlenemedi:', e.message)
      }
    }
  })
}

baglan().catch(async (e) => {
  await durumBildir('hata', { hata: e.message })
  process.exit(1)
})
