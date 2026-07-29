import image_svgviewer_png_output_1 from "@/imports/svgviewer-png-output-1.png";
import logoITS from "@/imports/Logo_ITS-Hitam.png";
import { useState, useRef, useEffect, useCallback, type ReactNode } from "react";
import { Send, Sparkles, Sun, Moon, MessageSquare, Plus, Clock, Trash2, Settings } from "lucide-react";
import { Link } from "react-router";
import { ImageWithFallback } from "@/app/components/figma/ImageWithFallback";
import { queryAgent, type AgentTrace } from "@/api";

/* ─── Types ─────────────────────────────────────────────────── */
type CarouselBook = {
  title: string;
  author: string;
  vibe?: string;
  kategori?: string;
  location: string;
  cover: string;
  sinopsis?: string;
};

type Message = {
  id: string;
  role: "user" | "assistant";
  text?: string;
  books?: CarouselBook[];
  meta?: { query_type: string; elapsed: number; hop: number };
  trace?: AgentTrace;
};

type Session = {
  id: string;
  title: string;
  timestamp: Date;
  messages: Message[];
};

/* ─── Cover pool (alternating) ──────────────────────────────── */
const COVERS = [
  "https://perpustakaan.jakarta.go.id/catalog-dispusip/uploaded_files/sampul_koleksi/original/Monograf/103861.jpg",
  "https://perpustakaan.jakarta.go.id/catalog-dispusip/uploaded_files/sampul_koleksi/original/Monograf/326214.png",
];
const cover = (i: number) => COVERS[i % 2];

/* ─── Real book data from OPAC query results ────────────────── */
const FONT_STEPS = [16, 18, 20, 22, 24] as const;

const INITIAL: Message[] = [{
  id: "0",
  role: "assistant",
  text: "Selamat datang di Agentic OPAC Explorer. Ketikkan topik, nama penulis, vibe, latar, atau kategori buku yang Anda cari — sistem AI kami akan menelusuri koleksi Perpustakaan Jakarta untuk Anda.",
}];

type Reply = { match: RegExp; text: string; meta: Message["meta"]; books: CarouselBook[] };

const REPLIES: Reply[] = [
  /* Q01 — Tere Liye (1-hop_author, 59.01s) */
  {
    match: /tere liye|tere-liye/i,
    text: "Halo pengunjung! Saya senang membantu Anda mencari buku karya Tere Liye di perpustakaan Jakarta. Berdasarkan data yang tersedia, ada beberapa pilihan buku yang menarik dari penulis ini.\n\nSaya merekomendasikan \"Komet\" oleh Tere Liye, sebuah buku dengan vibe petualangan, persahabatan, dan misteri. Buku ini memiliki latar belakang yang unik, yaitu dunia paralel. Anda bisa menemukan \"Komet\" di Perpustakaan Jakarta - PDS HB Jassin dan Perpustakaan Jakarta - Cikini.\n\nSelain itu, saya juga merekomendasikan \"Si Anak Kuat\" oleh Tere Liye dan Ahmad Rivai. Buku ini memiliki vibe romance dan inspiratif dengan latar pedesaan. Anda bisa menemukan \"Si Anak Kuat\" di Perpustakaan Jakarta Pusat - Petojo Enclek, Perpustakaan Jakarta - Cikini, dan Perpustakaan Jakarta - PDS HB Jassin.\n\nJika Anda ingin mencari buku lain dari Tere Liye, saya juga merekomendasikan \"Negeri Para Bedebah\" yang tersedia di Perpustakaan Jakarta - Kuningan dan Perpustakaan Jakarta - Cikini.\n\nSemoga rekomendasi saya membantu Anda menemukan buku yang sesuai dengan minat Anda!",
    meta: { query_type: "1-hop_author", elapsed: 59.01, hop: 1 },
    books: [
      { title: "Komet",                  author: "Tere Liye",                      vibe: "petualangan, persahabatan, misteri", location: "PDS HB Jassin, Cikini",                                cover: cover(0), sinopsis: "Setelah musuh besar kami lolos, dunia paralel dalam situasi genting. Hanya soal waktu, pertempuran besar akan terjadi. Bagaimana jika ribuan petarung yang bisa menghilang, mengeluarkan petir, termasuk teknologi maju lainnya muncul di permukaan Bumi? Buku ini berkisah tentang petualangan tiga sahabat. Raib bisa menghilang. Seli bisa mengeluarkan petir. Dan Ali bisa melakukan apa saja." },
      { title: "Si Anak Kuat",           author: "Tere Liye, Ahmad Rivai",         vibe: "romance, inspiratif",               location: "Petojo Enclek, Cikini, PDS HB Jassin, Tanjung Duren",   cover: cover(1), sinopsis: "Buku ini tentang Amelia, kisah anak yang memiliki mimpi-mimpi hebat untuk kampung tercintanya. Dari puluhan buku Tere Liye, serial buku ini adalah mahkotanya." },
      { title: "Negeri Para Bedebah",    author: "Tere Liye",                      vibe: "—",                                 location: "Kuningan, Cikini",                                     cover: cover(0) },
      { title: "Dia Adalah Kakakku",     author: "Tere Liye, Andriyati",           vibe: "biografi, keluarga",                location: "Petojo Enclek, Cikini, PDS HB Jassin, Tanjung Duren",   cover: cover(1), sinopsis: "Buat apa kamu memikirkan apa yang dipikirkan orang lain? Buat apa kamu mencemaskan apa yang akan dinilai orang lain? Kekhawatiran, juga kecemasan yang sejatinya mungkin tidak pernah ada. Dulu, sekarang, hingga kapan pun, dia adalah kakakku. Tentang seorang kakak yang mengorbankan apa pun agar adik-adiknya bisa sekolah. Tentang rasa sabar dan penerimaan. Tentang keluarga yang penuh perjuangan." },
      { title: "Pulang",                 author: "Tere Liye, Triana Rahmawati",    vibe: "biografi, kehidupan nyata",         location: "Gandaria Tengah, Tanjung Duren, PDS HB Jassin, Cikini", cover: cover(0), sinopsis: "Pulang berkisah tentang seorang anak talang di rimba hutan Sumatera, di antara rimbunnya Bukit Barisan, yang dipanggil si Bujang. Ia dititipkan pada seorang tauke. Dari seorang anak yang tidak memiliki alas kaki, si Bujang tumbuh menjadi seorang yang cerdas luar biasa dan menyelesaikan gelar dua master sekaligus. Padahal sampai usia 15 tahun ia tak mencecap bangku sekolah sedikit pun." },
      { title: "Negeri Di Ujung Tanduk", author: "Tere Liye",                      vibe: "—",                                 location: "Kuningan, Cikini, Petojo Enclek",                      cover: cover(1) },
      { title: "Rindu",                  author: "Tere Liye, Andriyati",           vibe: "—",                                 location: "Gandaria Tengah, Tanjung Duren, Petojo Enclek, Cikini", cover: cover(0) },
      { title: "Hafalan Shalat Delisa",  author: "Tere Liye",                      vibe: "—",                                 location: "PDS HB Jassin, Cikini, Tanjung Duren, Gandaria Tengah", cover: cover(1) },
    ],
  },

  /* Q02 — Thriller (1-hop_vibe, 22.97s) */
  {
    match: /thriller|mendebarkan|menegangkan/i,
    text: "Halo pengunjung! Saya senang membantu Anda mencari buku thriller mendebarkan di perpustakaan kami.\n\nSetelah memeriksa koleksi kami, saya menemukan bahwa \"Persimpangan\" oleh Hasan Aspahani memiliki nuansa thriller yang mendebarkan. Buku ini termasuk dalam kategori Novel dan tersedia di beberapa cabang perpustakaan kami, yaitu Perpustakaan Jakarta - PDS HB Jassin, Perpustakaan Jakarta Pusat - Petojo Enclek, Perpustakaan Jakarta - Kuningan, dan Perpustakaan Jakarta Timur - Jatinegara.\n\nJika Anda tertarik membaca \"Persimpangan\", saya sarankan untuk mengunjungi salah satu cabang perpustakaan kami yang tersedia. Saya yakin Anda akan menemukan buku ini di rak-rak kami!",
    meta: { query_type: "1-hop_vibe", elapsed: 22.97, hop: 1 },
    books: [
      { title: "Persimpangan", author: "Hasan Aspahani", kategori: "Novel", location: "PDS HB Jassin, Petojo Enclek, Kuningan, Jatinegara", cover: cover(0) },
    ],
  },

  /* Q03 — Berlatar kerajaan (1-hop_setting, 23.72s) */
  {
    match: /kerajaan|istana|raja|ratu|kerajaan/i,
    text: "Halo pengunjung! Kami senang membantu kamu mencari novel berlatar kerajaan. Berdasarkan ketersediaan buku di perpustakaan kami, ada beberapa pilihan yang menarik untuk kamu.\n\nKamu bisa memilih \"Recollection : Ther Melian\" oleh Shienny dan Grace Situngkir, yang memiliki vibe thriller, romance, dan misteri. Buku ini tersedia di Perpustakaan Jakarta - Cikini. Atau, jika kamu ingin novel dengan latar kerajaan dan sejarah, \"Laksamana Malahayati : Sang Perempuan Keumala\" oleh A. Ariobimo Nusantara dan Endang Moerdopo bisa menjadi pilihan yang tepat. Buku ini tersedia di beberapa lokasi perpustakaan, termasuk Perpustakaan Jakarta - Cikini.\n\nKedua buku ini memiliki latar kerajaan sebagai salah satu elemen utama cerita. Kami harap kamu menemukan novel yang sesuai dengan selera bacaanmu!",
    meta: { query_type: "1-hop_setting", elapsed: 23.72, hop: 1 },
    books: [
      { title: "Recollection: Ther Melian",                       author: "Shienny, Grace Situngkir",              vibe: "thriller, romance, misteri",     location: "Cikini",                                         cover: cover(0), sinopsis: "Saat berburu, Elya menemukan seorang pemuda yang sekarat di antara jasad prajurit Falthemnar dan membawanya pulang untuk dirawat. Karena pria itu tidak mengingat jati dirinya, maka dia diberi nama Lucca, yang artinya Anak Hilang. Sementara itu, pembunuh misterius sedang berkeliaran di Dominia dan mengancam jalannya Festival Musim Kemarau." },
      { title: "Elang Menoreh: Perjalanan Purwa Kala",            author: "A. Mellyora, Wiwien Wintarto",          vibe: "thriller, misteri, petualangan", location: "Tanjung Duren, Cikini",                          cover: cover(1), sinopsis: "Usai menamatkan ajaran ilmu bela diri di Padepokan Menoreh, Nara ditugaskan Empu Soca untuk membantu mengawal Demang Begelen Ki Martawuni dari ancaman gembong perampok Bango Lampar. Nara pun harus berurusan dengan penguasa Mataram dan terseret dalam pusaran konflik antara Mataram dan para adipati Bang Wetan." },
      { title: "Pasangan Traveling",                              author: "Winny Gunarti, Pasangantraveling.com", vibe: "petualangan, romance",           location: "Cikini, Gandaria Tengah",                        cover: cover(0), sinopsis: "Ada 22 destinasi di buku ini yang bisa Anda jadikan inspirasi untuk perjalanan berikutnya. Anda akan diajak menikmati keheningan yang romantis di Kampung Sampireun, Garut, berjemur berdua di pantai-pantai Lombok yang menawan, dan melewatkan malam di kereta dari Paris ke Venesia." },
      { title: "Princess Academy: Putri Sabari Putri Pemberani",  author: "Oyasujiwo, Kumatyo",                   vibe: "misteri, romance",               location: "Cikini",                                         cover: cover(1), sinopsis: "Para putri Princess Academy kembali mementaskan Opera Dongeng. Kali ini, cerita yang diangkat berasal dari Sumatera Barat. Rosmalina menjadi peran utama. Ia akan berperan sebagai Putri Sabai nan Aluih. Sabai nan Aluih adalah sosok putri pemberani yang melawan ketidakadilan." },
      { title: "Laksamana Malahayati: Sang Perempuan Keumala",    author: "A. Ariobimo Nusantara, Endang Moerdopo", vibe: "romance, sejarah",              location: "Cikini, Jatinegara, PDS HB Jassin",              cover: cover(0), sinopsis: "Novel ini memukau, justru karena tidak sekadar silau pada masa lampau, melainkan dengan elok dan empati yang menyentuh menggambarkan perempuan pahlawan Aceh Keumalahayati sang Laksamana secara utuh." },
      { title: "Princess Academy: Kanaya Putri Pantang Menyerah", author: "Oyasujiwo, Kumatyo",                   vibe: "misteri, romance",               location: "Petojo Enclek, Cikini, Gandaria Tengah",         cover: cover(1), sinopsis: "Opera Dongeng Princess Academy kembali dipentaskan. Odelia yang jadi peran utamanya. Kali ini, kisah yang diangkat berasal dari Sulawesi Tenggara, yaitu Kanaya. Ia adalah sosok putri yang rajin dan pantang menyerah." },
      { title: "Kumpulan Cerita Asli Indonesia Vol.2",            author: "Tim Elex, Maria Wuri Anjani, Yunianto", vibe: "legenda, misteri",              location: "Cikini",                                         cover: cover(0), sinopsis: "Buku cerita asli Indonesia dalam bentuk dongeng dan legenda yang sudah ada di masyarakat Indonesia sejak zaman dahulu. Umumnya cerita yang berisikan keteladanan, budi pekerti, semangat kepahlawanan, kejujuran, dan kesabaran ini disampaikan secara turun-temurun dan dari mulut ke mulut." },
      { title: "Cerita Asli Nusantara",                           author: "Asteria Renny, Faza",                  vibe: "misteri, sejarah",               location: "Tanjung Duren, Petojo Enclek, Kuningan, Cikini", cover: cover(1), sinopsis: "Nusantara kita yang tercinta menyimpan begitu banyak kisah dan cerita yang telah diceritakan secara turun temurun oleh para leluhur. Cerita itu merupakan warisan yang perlu kita jaga karena juga merupakan warisan budaya yang memuat nilai-nilai luhur." },
    ],
  },

  /* Q04 — Cerita Anak (1-hop_category, 22.29s) */
  {
    match: /cerita anak|anak-anak|anak kecil|anak saya|dongeng/i,
    text: "Halo pengunjung! Saya senang membantu Anda mencari buku Cerita Anak untuk anak Anda.\n\nSetelah memeriksa koleksi kami, saya merekomendasikan beberapa pilihan yang menarik. Pertama, ada \"Kecil-kecil Punya Karya : Magic Cookies\" oleh Yuni Mulyawati, Muthia Fadhila Khairunnisa, dan Ridwan Fauzy. Buku ini tersedia di Perpustakaan Jakarta - Cikini dan Perpustakaan Jakarta Pusat - Petojo Enclek.\n\nKedua, saya juga merekomendasikan \"Kumpulan Dongeng Bijak Dari Asia Timur\" oleh Diba dan Wiwid. Buku ini memiliki vibe moral dan pendidikan yang sangat cocok untuk anak-anak. Anda bisa menemukan buku ini di beberapa lokasi, termasuk Perpustakaan Jakarta Barat - Tanjung Duren dan Perpustakaan Jakarta - Cikini.\n\nJika Anda ingin mencari sesuatu yang lebih unik, saya juga merekomendasikan \"Kumpulan Cerita : Kurcaci Dan Peri\" oleh Asteria Renny. Buku ini memiliki vibe misteri dan petualangan yang menarik, dengan latar belakang dunia imajinatif dan hutan desa. Anda bisa menemukan buku ini di Perpustakaan Jakarta Timur - Jatinegara dan Perpustakaan Jakarta Selatan - Gandaria Tengah.\n\nSemoga rekomendasi saya membantu!",
    meta: { query_type: "1-hop_category", elapsed: 22.29, hop: 1 },
    books: [
      { title: "Kecil-kecil Punya Karya: Magic Cookies", author: "Yuni Mulyawati, Muthia Fadhila Khairunnisa, Ridwan Fauzy", kategori: "Cerita Anak",               location: "Cikini, Petojo Enclek",              cover: cover(0) },
      { title: "Kumpulan Cerita Pahlawan Super",          author: "Dhita Kurniawan",                                          vibe: "superhero, aksi, petualangan",  location: "Gandaria Tengah, Tanjung Duren, Cikini", cover: cover(1), sinopsis: "Buku ini bercerita tentang aksi para pahlawan super yang gagah berani. Mereka menumpas kejahatan dengan semangat. Para pahlawan super tersebut layak diteladani karena selalu menolong tanpa pamrih, penuh tanggung jawab, sopan, dan pastinya selalu berbuat baik untuk sesama." },
      { title: "Kumpulan Dongeng Bijak Dari Asia Timur",  author: "Diba, Wiwid",                                              vibe: "moral, pendidikan",             location: "Tanjung Duren, Cikini, Petojo Enclek, Koja", cover: cover(0), sinopsis: "Dongeng adalah bacaan yang bagus untuk perkembangan kecerdasan anak. Banyak sekali pengetahuan budaya dalam dongeng-dongeng ini. Ada dongeng Batu Ajaib, Rahasia Pulau Dok, Kipas Merah dan Kipas Biru, Putri Bari, dan lain-lain. Setiap dongeng dilengkapi ilustrasi menarik dan penuh warna." },
      { title: "Kumpulan Cerita: Kurcaci Dan Peri",       author: "Asteria Renny",                                            vibe: "misteri, anak-anak, petualangan", location: "Jatinegara, Gandaria Tengah",       cover: cover(1), sinopsis: "Kurcaci dan peri hidup dalam dunia yang berbeda. Tapi, di dalam buku ini mereka bisa hidup berdampingan. Memang kadang mereka berselisih paham, tapi akhirnya mereka kembali bersahabat. Ada 15 dongeng kurcaci dan peri di sini yang akan menghiburmu dengan ilustrasi yang cerah dan menyenangkan." },
    ],
  },

  /* Q05 — DDC 641 Kuliner (1-hop_ddc, 22.81s) */
  {
    match: /ddc 641|kuliner|masakan|resep|makanan/i,
    text: "Halo pengunjung! Saya senang membantu Anda mencari buku tentang kuliner dan masakan dengan klasifikasi DDC 641.\n\nSetelah memeriksa koleksi kami, saya menemukan beberapa pilihan yang mungkin menarik bagi Anda. Pertama, ada \"Homemade Snacks & Desserts Ala Xanders's Kitchen\" oleh Junita dan Intarina Hardiman. Buku ini berisi resep-resep kreatif untuk camilan dan dessert yang bisa dibuat di rumah. Kedua, ada juga \"60 Resep Paket Lauk Ikan Dan Sambal\" oleh Edward dan Ratu Afifah, yang menawarkan variasi resep masakan laut yang lezat.\n\nKedua buku ini tersedia di Perpustakaan Jakarta - Cikini. Jika Anda ingin mencari lebih banyak pilihan, saya juga bisa merekomendasikan \"Jakarta Street Food\" oleh Intarina Hardiman, yang berisi tentang kuliner khas Jakarta. Buku ini juga tersedia di Perpustakaan Jakarta - Cikini.\n\nSemoga informasi ini membantu! Jika Anda memiliki pertanyaan lebih lanjut atau ingin mencari buku lain, jangan ragu untuk bertanya.",
    meta: { query_type: "1-hop_ddc", elapsed: 22.81, hop: 1 },
    books: [
      { title: "Homemade Snacks & Desserts Ala Xanders's Kitchen", author: "Junita, Intarina Hardiman",              kategori: "Aneka Resep - Hidangan Campuran", location: "Cikini, Kuningan",                                    cover: cover(0), sinopsis: "Buku ini diterbitkan untuk memenuhi permintaan para follower penulis di akun Instagram @xanderskitchen yang saat ini telah mencapai 625K lebih. Buku ini berisi 135 resep pilihan snack dan dessert meliputi Cake, Kue Kering, Kue Basah Tradisional, Snack Populer, Roti, Bubur Manis, Puding, Minuman, dan Sajian Segar Buah & Sayuran." },
      { title: "Cookies Decorating: 50 Desain Cookies Natal",      author: "Etha Margaretha Trezise, Irfan Kwandow", kategori: "Kue, Natal",              location: "Cikini, Gandaria Tengah, Kuningan",                   cover: cover(1), sinopsis: "50 Desain Cookies Natal menyuguhkan tutorial secara detail dan lengkap dengan foto-foto step-by-step yang akan mempermudah pembaca untuk mempelajari dan mempraktikkan. Mencakup resep membuat cookies dan royal icing, pengenalan peralatan, teknik mendekorasi cookies, tip-tip yang bermanfaat, dan 50 desain cookies bertema Natal yang lucu dan menarik." },
      { title: "60 Resep Kue Kering Anti Gagal",                   author: "Tim Dapur Media",                        kategori: "Resep, Kue",              location: "Cikini",                                              cover: cover(0), sinopsis: "Membuat kue kering dianggap berhasil bila kue yang dihasilkan bentuknya bagus, rasanya enak dan renyah alias tidak keras. Adakalanya kue yang dihasilkan bentuknya bagus, namun keras. Begitu juga sebaliknya, kue yang dihasilkan sangat renyah dan enak rasanya, namun memiliki bentuk yang tidak keruan." },
      { title: "50 Resep Puding Coklat Pilihan",                   author: "Iva Hardiana, Intarina Hardiman",        kategori: "Masakan",                 location: "Cikini",                                              cover: cover(1), sinopsis: "Puding, disukai. Cokelat, disukai. Puding Cokelat? Paduan dahsyat! Favorit keluarga tercinta. Tak tanggung-tanggung, buku ini merangkum 50 resep puding cokelat berbahan dasar agar-agar bubuk, jeli instan bubuk, dan puding susu instan bubuk, dan cokelat." },
      { title: "Resep Favorit Ny. Liem Pempek",                    author: "Yudho Asmoro, Intarina Hardiman",        kategori: "Pempek, Masakan",         location: "Gandaria Tengah, Cikini, Jatinegara",                 cover: cover(0), sinopsis: "Berisi lebih dari 20 resep Pempek Favorit yang diajarkan di Kursus Masak Ny. Liem, seperti Pempek Kapal Selam, Pempek Lenjer, Pempek Kulit, Pempek Keriting, dan Pempek Adaan. Kursus Masak Ny. Liem merupakan tempat kursus masak yang sangat terkenal di kota Bandung dengan jumlah murid mencapai ribuan, tersebar di seluruh Indonesia." },
      { title: "60 Resep Paket Lauk Ikan Dan Sambal",              author: "Edward, Ratu Afifah",                    kategori: "Makanan Laut",            location: "Cikini, Koja, Kuningan, Tanjung Duren, Petojo Enclek", cover: cover(1) },
      { title: "Jakarta Street Food",                               author: "Intarina Hardiman",                      kategori: "Makanan",                 location: "Cikini, Gandaria Tengah",                             cover: cover(0), sinopsis: "Gaya hidup kuliner 12 juta masyarakatnya yang sangat aktif, telah menempatkan Jakarta sebanding dengan kota-kota besar di dunia lainnya, seperti New York, Berlin, Singapura, dan Los Angeles. Keberagaman kuliner yang tersaji di Jakarta sebagai melting pot dari banyak suku dan bangsa dunia adalah jejak sejarah Jakarta sebagai kota pusat perdagangan terbesar di abad ke-16 hingga ke-18." },
      { title: "Resep Andalan Ny. Liem: Kreasi Puding Lapis Gaya Baru", author: "Yudho Asmoro, Intarina Hardiman", kategori: "Resep Masakan, Puding",   location: "Cikini",                                              cover: cover(1), sinopsis: "Berisi 33 resep Kreasi Puding Lapis Gaya Baru yang diajarkan di Kursus Masak Ny. Liem seperti Honey Green Pudding, Avocado Coffee Dessert, Blueberry Yoghurt Creme, Puding Pandan Lapis Kaca, dan Puding Jambu." },
    ],
  },

  /* Q06 — Bahasa Inggris (1-hop_language, 18.44s) */
  {
    match: /bahasa inggris|english|inggris/i,
    text: "Halo pengunjung! Kami senang membantu Anda mencari buku dalam bahasa Inggris.\n\nDari daftar kami, ada beberapa pilihan yang mungkin sesuai dengan kebutuhan Anda. Pertama-tama, mari kita lihat \"One Fish, Two Fish, Red Fish, Blue Fish\" oleh Unknown. Buku ini termasuk kategori Bahasa Inggris - Bacaan Kanak-Kanak dan tersedia di Perpustakaan Jakarta - Cikini.\n\nSelain itu, Anda juga bisa mempertimbangkan \"Disney Magic English 24 : Mountains\" oleh Unknown. Buku ini juga dalam bahasa Inggris dan khusus untuk anak-anak, dengan tema yang menarik tentang gunung. Tersedia di Perpustakaan Jakarta - Cikini.\n\nTerakhir, ada \"Fox In Socks\" oleh Unknown yang mungkin menarik perhatian Anda. Buku ini juga dalam bahasa Inggris dan termasuk kategori Bahasa Inggris - Buku Anak-Anak. Tersedia di Perpustakaan Jakarta - Cikini.\n\nSemoga informasi ini membantu Anda menemukan buku yang tepat!",
    meta: { query_type: "1-hop_language", elapsed: 18.44, hop: 1 },
    books: [
      { title: "Pandora's Box",                    author: "J. Solomon, Julia Golding",  kategori: "Dongeng Anak",                    location: "Cikini, Tanjung Duren", cover: cover(0) },
      { title: "One Fish, Two Fish, Red Fish, Blue Fish", author: "—",                  kategori: "Bahasa Inggris - Bacaan Kanak-Kanak", location: "Cikini",            cover: cover(1) },
      { title: "Disney Magic English 24: Mountains", author: "—",                       kategori: "Bahasa Inggris - Bacaan Kanak-Kanak", location: "Cikini",            cover: cover(0) },
      { title: "Lego Nexo Knights: Meet The Knights", author: "Julia March, Pamela Ann", kategori: "Komik Anak",                      location: "Cikini",              cover: cover(1) },
      { title: "Fox In Socks",                      author: "—",                         kategori: "Bahasa Inggris - Buku Anak-Anak", location: "Cikini",              cover: cover(0) },
    ],
  },

  /* Q07 — Tokoh Naura (1-hop_character, 21.85s) */
  {
    match: /naura|tokoh naura/i,
    text: "Halo pengunjung! Kami senang membantu Anda mencari buku dengan tokoh Naura.\n\nSetelah memeriksa koleksi kami, kami menemukan beberapa buku yang mungkin sesuai dengan kebutuhan Anda. \"Seri Anak Hebat : Aku Mau Tidur Sendiri\" oleh Nurhadiansyah dan Teguh Affandi adalah salah satu pilihan yang menarik. Buku ini memiliki vibe keluarga dan anak-anak, serta latar rumah. Buku ini tersedia di beberapa cabang perpustakaan kami, yaitu Perpustakaan Jakarta Barat - Tanjung Duren, Perpustakaan Jakarta Pusat - Petojo Enclek, Perpustakaan Jakarta - Cikini, dan Perpustakaan Jakarta Selatan - Gandaria Tengah.\n\nSelain itu, kami juga menemukan \"Seri Anak Hebat : Aku Sayang Kakakku\" oleh Noor H. Dee yang memiliki vibe remaja dan keluarga. Buku ini juga memiliki latar rumah dan perkotaan. Buku ini tersedia di beberapa cabang perpustakaan kami, yaitu Perpustakaan Jakarta Barat - Tanjung Duren, Perpustakaan Jakarta Pusat - Petojo Enclek, Perpustakaan Jakarta Selatan - Gandaria Tengah, dan Perpustakaan Jakarta - Cikini.\n\nJika Anda ingin mencari buku lain dengan tokoh Naura, silakan hubungi kami untuk informasi lebih lanjut. Kami senang membantu!",
    meta: { query_type: "1-hop_character", elapsed: 21.85, hop: 1 },
    books: [
      { title: "Seri Anak Hebat: Aku Mau Tidur Sendiri", author: "Nurhadiansyah, Teguh Affandi", vibe: "keluarga, anak-anak",  location: "Tanjung Duren, Petojo Enclek, Cikini, Gandaria Tengah", cover: cover(0) },
      { title: "Seri Anak Hebat: Aku Belajar 123",        author: "Noor H. Dee",                  vibe: "belajar, pendidikan",  location: "Tanjung Duren, Cikini, Petojo Enclek",                  cover: cover(1) },
      { title: "Aku Bilang Terima Kasih",                  author: "Noor H. Dee, Nurhadiansyah",  vibe: "keluarga, kebaikan",   location: "Petojo Enclek, Cikini, Jatinegara, Koja",               cover: cover(0) },
      { title: "Seri Anak Hebat: Aku Sayang Kakakku",     author: "Noor H. Dee",                  vibe: "remaja, keluarga",     location: "Tanjung Duren, Petojo Enclek, Gandaria Tengah, Cikini", cover: cover(1) },
    ],
  },
];

const FALLBACK: Reply = {
  match: /.*/,
  text: "Berikut beberapa rekomendasi dari koleksi Perpustakaan Jakarta berdasarkan kueri Anda:",
  meta: { query_type: "vector_search", elapsed: 18.5, hop: 1 },
  books: [
    { title: "Komet",                              author: "Tere Liye",                  vibe: "petualangan, misteri",    location: "PDS HB Jassin, Cikini",       cover: cover(0) },
    { title: "Pulang",                             author: "Tere Liye",                  vibe: "biografi, kehidupan nyata", location: "PDS HB Jassin, Cikini",     cover: cover(1) },
    { title: "Laksamana Malahayati",               author: "A. Ariobimo Nusantara",      vibe: "romance, sejarah",        location: "Jatinegara, PDS HB Jassin",   cover: cover(0) },
    { title: "Persimpangan",                       author: "Hasan Aspahani",             kategori: "Novel",               location: "PDS HB Jassin, Kuningan",     cover: cover(1) },
    { title: "Jakarta Street Food",                author: "Intarina Hardiman",           kategori: "Makanan",             location: "Cikini, Gandaria Tengah",     cover: cover(0) },
    { title: "Cerita Asli Nusantara",              author: "Asteria Renny, Faza",         vibe: "misteri, sejarah",        location: "Tanjung Duren, Kuningan",     cover: cover(1) },
  ],
};

const SUGGESTIONS = [
  "Buku karya Tere Liye",
  "Novel berlatar kerajaan",
  "Buku cerita anak / dongeng",
  "Kuliner & masakan DDC 641",
  "Buku bahasa Inggris",
  "Buku dengan tokoh Naura",
];

/* ─── helpers ────────────────────────────────────────────────── */
function makeSession(messages: Message[] = INITIAL): Session {
  const first = messages.find(m => m.role === "user");
  return { id: `s${Date.now()}`, title: first ? first.text!.slice(0, 46) : "Sesi baru", timestamp: new Date(), messages };
}

/* Chat lives in React state, so routing to /admin and back remounts App and
 * would wipe it. Persist to sessionStorage (per browser tab) and restore on
 * mount so the conversation survives the round-trip. */
const SESSION_STORE_KEY = "opac-explorer-chat-v1";

function loadPersistedChat(): { sessions: Session[]; activeId: string } | null {
  try {
    const raw = sessionStorage.getItem(SESSION_STORE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { sessions?: Session[]; activeId?: string };
    if (!parsed?.sessions?.length) return null;
    // Revive timestamps (JSON turned Date → ISO string) so relTime() works.
    const sessions = parsed.sessions.map(s => ({ ...s, timestamp: new Date(s.timestamp) }));
    const activeId = sessions.some(s => s.id === parsed.activeId) ? parsed.activeId! : sessions[0].id;
    return { sessions, activeId };
  } catch {
    return null;
  }
}

function relTime(d: Date) {
  const min = Math.floor((Date.now() - d.getTime()) / 60000);
  if (min < 1) return "Baru saja";
  if (min < 60) return `${min} menit lalu`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} jam lalu`;
  return d.toLocaleDateString("id-ID", { day: "numeric", month: "short" });
}

/* ─── Carousel card ──────────────────────────────────────────── */
function CarouselCard({ book, hc, fs }: { book: CarouselBook; hc: boolean; fs: number }) {
  const [imgErr, setImgErr] = useState(false);
  const [hovered, setHovered] = useState(false);
  const tag = book.vibe ?? book.kategori ?? "Koleksi";

  return (
    <div
      className="shrink-0 rounded-2xl overflow-hidden transition-all duration-200 hover:-translate-y-1 hover:shadow-xl"
      style={{
        flex: "0 0 calc(20% - 10px)",
        minWidth: 110,
        aspectRatio: "2 / 3",
        position: "relative",
        background: "#1a1a4e",
        border: hc ? "2px solid #1a1a2e" : "1px solid rgba(255,255,255,0.18)",
        boxShadow: hc ? "none" : "0 4px 18px rgba(0,0,0,0.22)",
        cursor: "pointer",
      }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Cover image */}
      {!imgErr ? (
        <img
          src={book.cover}
          alt={`Sampul — ${book.title}`}
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" }}
          onError={() => setImgErr(true)}
        />
      ) : (
        <div style={{ position: "absolute", inset: 0, background: "linear-gradient(160deg,#1a1a4e,#3730a3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 36 }}>
          📖
        </div>
      )}

      {/* Top scrim + category badge */}
      <div
        style={{
          position: "absolute", top: 0, left: 0, right: 0,
          background: "linear-gradient(to bottom, rgba(0,0,0,0.72) 0%, rgba(0,0,0,0.30) 60%, transparent 100%)",
          padding: "10px 10px 20px",
        }}
      >
        <span
          style={{
            display: "inline-block",
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: "0.07em",
            textTransform: "uppercase" as const,
            color: "#ffffff",
            background: "rgba(108,99,255,0.75)",
            border: "1px solid rgba(255,255,255,0.25)",
            borderRadius: 6,
            padding: "2px 7px",
            backdropFilter: "blur(4px)",
            WebkitBackdropFilter: "blur(4px)",
            lineHeight: 1.6,
            maxWidth: "100%",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap" as const,
          }}
        >
          {tag.split(",")[0].trim()}
        </span>
      </div>

      {/* Bottom scrim + title + author */}
      <div
        style={{
          position: "absolute", bottom: 0, left: 0, right: 0,
          background: "linear-gradient(to top, rgba(0,0,0,0.88) 0%, rgba(0,0,0,0.60) 55%, transparent 100%)",
          padding: "28px 10px 12px",
          transition: "opacity 0.25s ease",
          opacity: hovered ? 0 : 1,
        }}
      >
        <p
          style={{
            fontSize: Math.max(fs - 4, 12),
            fontWeight: 700,
            color: "#ffffff",
            lineHeight: 1.25,
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
            textShadow: "0 1px 4px rgba(0,0,0,0.6)",
            marginBottom: 4,
          }}
        >
          {book.title}
        </p>
        <p
          style={{
            fontSize: Math.max(fs - 6, 10),
            fontWeight: 500,
            color: "rgba(255,255,255,0.80)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap" as const,
            textShadow: "0 1px 3px rgba(0,0,0,0.5)",
          }}
        >
          {book.author}
        </p>
      </div>

      {/* Hover overlay — sinopsis */}
      <div
        style={{
          position: "absolute", inset: 0,
          background: "linear-gradient(160deg, rgba(26,18,60,0.96) 0%, rgba(76,54,180,0.94) 100%)",
          backdropFilter: "blur(2px)",
          WebkitBackdropFilter: "blur(2px)",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "12px 11px 12px",
          opacity: hovered ? 1 : 0,
          transition: "opacity 0.25s ease",
          pointerEvents: hovered ? "auto" : "none",
        }}
      >
        {/* Header */}
        <div>
          <span
            style={{
              display: "inline-block",
              fontSize: 9, fontWeight: 700,
              letterSpacing: "0.07em",
              textTransform: "uppercase" as const,
              color: "#ffffff",
              background: "rgba(255,255,255,0.15)",
              borderRadius: 5,
              padding: "2px 6px",
              marginBottom: 8,
              maxWidth: "100%",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap" as const,
            }}
          >
            {tag.split(",")[0].trim()}
          </span>
          <p style={{ fontSize: Math.max(fs - 4, 12), fontWeight: 700, color: "#ffffff", lineHeight: 1.25, marginBottom: 4 }}>
            {book.title}
          </p>
          <p style={{ fontSize: Math.max(fs - 6, 10), color: "rgba(255,255,255,0.70)", fontWeight: 500, marginBottom: 10, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" as const }}>
            {book.author}
          </p>
          {book.sinopsis && (
            <p
              style={{
                fontSize: Math.max(fs - 6, 10),
                color: "rgba(255,255,255,0.88)",
                lineHeight: 1.55,
                display: "-webkit-box",
                WebkitLineClamp: 7,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
              }}
            >
              {book.sinopsis}
            </p>
          )}
        </div>

        {/* Footer — location */}
        <div
          style={{
            borderTop: "1px solid rgba(255,255,255,0.15)",
            paddingTop: 8,
            marginTop: 8,
          }}
        >
          <p style={{ fontSize: Math.max(fs - 5, 12), color: "rgba(255,255,255,0.75)", lineHeight: 1.5 }}>
            <span style={{ fontWeight: 700, color: "rgba(255,255,255,0.90)" }}>Tersedia di: </span>
            {book.location}
          </p>
        </div>
      </div>
    </div>
  );
}

/* ─── Book carousel (the AI response card) ───────────────────── */
function BookCarousel({ books, meta, hc, fs }: { books: CarouselBook[]; meta?: Message["meta"]; hc: boolean; fs: number }) {
  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{
        background: hc ? "#ffffff" : "rgba(255,255,255,0.55)",
        backdropFilter: hc ? "none" : "blur(20px)",
        WebkitBackdropFilter: hc ? "none" : "blur(20px)",
        border: hc ? "2px solid #1a1a2e" : "1px solid rgba(255,255,255,0.82)",
        boxShadow: hc ? "none" : "0 4px 24px rgba(108,99,255,0.09)",
      }}
    >
      {/* Header bar */}
      <div
        className="flex items-center justify-between px-4 py-3"
        style={{ borderBottom: hc ? "1.5px solid #1a1a2e" : "1px solid rgba(108,99,255,0.10)" }}
      >
        <div className="flex items-center gap-2">
          <span style={{ fontSize: Math.max(fs - 5, 11), fontWeight: 700, color: hc ? "#0a0920" : "#1a1a2e", letterSpacing: "0.01em" }}>
            Top {books.length} Rekomendasi
          </span>
        </div>
        {meta && (
          <div className="flex items-center gap-2">
            <span
              className="px-2 py-0.5 rounded-full"
              style={{ fontSize: 9, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", background: hc ? "rgba(76,70,196,0.10)" : "rgba(108,99,255,0.10)", color: hc ? "#1a1a2e" : "#5b54e8", border: hc ? "1px solid #4c46c4" : "none" }}
            >
              {meta.query_type.replace(/_/g, " ")}
            </span>
            <span style={{ fontSize: 9, color: "#9896c8" }}>{meta.hop}-hop · {meta.elapsed}s</span>
          </div>
        )}
      </div>

      {/* Scrollable carousel */}
      <div
        className="px-4 py-4"
        style={{
          display: "flex",
          flexDirection: "row",
          gap: 12,
          overflowX: "auto",
          scrollbarWidth: "none",
        }}
      >
        <style>{`div::-webkit-scrollbar{display:none}`}</style>
        {books.map((b, i) => (
          <CarouselCard key={i} book={b} hc={hc} fs={fs} />
        ))}
      </div>
    </div>
  );
}

/* ─── Typing dots ─────────────────────────────────────────────── */
function Dots({ hc }: { hc: boolean }) {
  return (
    <div className="flex items-center gap-2 px-5 py-3.5 rounded-2xl w-fit"
      style={{ background: hc ? "#ffffff" : "rgba(255,255,255,0.60)", border: hc ? "2px solid #1a1a2e" : "1px solid rgba(255,255,255,0.82)" }}>
      {[0,1,2].map(i => (
        <span key={i} className="w-2.5 h-2.5 rounded-full animate-bounce"
          style={{ background: hc ? "#1a1a2e" : "#8b5cf6", animationDelay: `${i*0.15}s` }} />
      ))}
    </div>
  );
}

/* ─── Minimal Markdown renderer (bold + bullet/numbered lists + spacing) ─
 * The responder emits clean Markdown (**bold** titles, "- " lists). We render
 * it so bold actually shows and list items get real spacing — no raw asterisks.
 * Intentionally tiny (no external dep): handles **bold**, bullet/numbered lists,
 * and blank-line-separated paragraphs. Good enough for the responder's output. */
function mdInline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) => {
    const m = /^\*\*([^*]+)\*\*$/.exec(part);
    return m ? <strong key={i}>{m[1]}</strong> : <span key={i}>{part}</span>;
  });
}

function Markdown({ text, fs }: { text: string; fs: number }) {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const isItem = (l: string) => /^\s*(?:[-*]|\d+\.)\s+/.test(l);
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    if (!lines[i].trim()) { i++; continue; }
    if (isItem(lines[i])) {
      const ordered = /^\s*\d+\.\s+/.test(lines[i]);
      const items: string[] = [];
      while (i < lines.length) {
        if (isItem(lines[i])) { items.push(lines[i].replace(/^\s*(?:[-*]|\d+\.)\s+/, "")); i++; }
        else if (!lines[i].trim()) { i++; }              // skip blank lines within a list
        else break;
      }
      const Tag = ordered ? "ol" : "ul";
      blocks.push(
        <Tag key={key++} style={{ margin: "4px 0 12px", paddingLeft: 22 }}>
          {items.map((it, j) => (
            <li key={j} style={{ lineHeight: 1.65, marginBottom: 8 }}>{mdInline(it)}</li>
          ))}
        </Tag>,
      );
    } else {
      const para: string[] = [];
      while (i < lines.length && lines[i].trim() && !isItem(lines[i])) { para.push(lines[i]); i++; }
      blocks.push(
        <p key={key++} style={{ margin: "0 0 10px", lineHeight: 1.65 }}>{mdInline(para.join(" "))}</p>,
      );
    }
  }
  return <div style={{ fontSize: fs }}>{blocks}</div>;
}

/* ─── Agent thinking trace (collapsible) ─────────────────────── */
function ThinkingPanel({ trace, hc, fs }: { trace: AgentTrace; hc: boolean; fs: number }) {
  const [open, setOpen] = useState(false);
  const steps = trace.toolChain ?? [];
  if (!steps.length) return null;
  return (
    <div
      className="rounded-2xl overflow-hidden"
      style={{
        border: hc ? "2px solid #1a1a2e" : "1px solid rgba(108,99,255,0.20)",
        background: hc ? "#ffffff" : "rgba(255,255,255,0.45)",
        backdropFilter: hc ? "none" : "blur(20px)",
        WebkitBackdropFilter: hc ? "none" : "blur(20px)",
      }}
    >
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-2 px-4 py-2.5"
        style={{
          fontSize: Math.max(fs - 5, 11), fontWeight: 700,
          color: hc ? "#1a1a2e" : "#5b54e8", background: "transparent",
          cursor: "pointer", border: "none",
        }}
        aria-expanded={open}
      >
        <span>Proses berpikir agen · {steps.length} langkah</span>
        <span style={{ marginLeft: "auto", fontSize: 12 }}>{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <ol
          className="px-5 pb-3 pt-1"
          style={{
            margin: 0, paddingLeft: 28, listStyle: "decimal",
            fontSize: Math.max(fs - 6, 10), lineHeight: 1.7,
            color: hc ? "#33324a" : "#4a4670",
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          }}
        >
          {steps.map((s, i) => (
            <li key={i} style={{ marginBottom: 3, wordBreak: "break-word" }}>{s}</li>
          ))}
        </ol>
      )}
    </div>
  );
}

/* ─── Message rows ───────────────────────────────────────────── */
function AiRow({ msg, fs, hc }: { msg: Message; fs: number; hc: boolean }) {
  return (
    <div className="flex gap-3 items-start" style={{ maxWidth: "94%" }}>
      <div className="shrink-0 w-8 h-8 rounded-xl flex items-center justify-center mt-0.5"
        style={{ background: hc ? "#1a1a2e" : "linear-gradient(135deg,#6c63ff,#a78bfa)" }}>
        <Sparkles size={15} color="white" />
      </div>
      <div className="flex flex-col gap-2 flex-1 min-w-0">
        {msg.text && (
          <div className="px-5 py-4 rounded-2xl"
            style={{ fontSize: fs, lineHeight: 1.6, letterSpacing: "0.02em", color: hc ? "#0a0920" : "#0f0e1a", background: hc ? "#ffffff" : "rgba(255,255,255,0.60)", backdropFilter: hc ? "none" : "blur(20px)", WebkitBackdropFilter: hc ? "none" : "blur(20px)", border: hc ? "2px solid #1a1a2e" : "1px solid rgba(255,255,255,0.84)", boxShadow: hc ? "none" : "0 2px 14px rgba(108,99,255,0.06)" }}>
            <Markdown text={msg.text} fs={fs} />
          </div>
        )}
        {msg.books && <BookCarousel books={msg.books} meta={msg.meta} hc={hc} fs={fs} />}
        {msg.trace && <ThinkingPanel trace={msg.trace} hc={hc} fs={fs} />}
      </div>
    </div>
  );
}

function UserRow({ text, fs, hc }: { text: string; fs: number; hc: boolean }) {
  return (
    <div className="flex justify-end">
      <div className="px-5 py-4 rounded-2xl"
        style={{ fontSize: fs, lineHeight: 1.6, letterSpacing: "0.02em", maxWidth: "78%", color: "#ffffff", background: hc ? "#1a1a2e" : "linear-gradient(135deg,#4c46c4,#6c63ff)", boxShadow: hc ? "none" : "0 4px 18px rgba(108,99,255,0.30)" }}>
        {text}
      </div>
    </div>
  );
}

/* ─── Accessibility button ───────────────────────────────────── */
function A11yBtn({ label, onClick, active, hc, children }: { label: string; onClick: () => void; active?: boolean; hc: boolean; children: React.ReactNode }) {
  return (
    <button aria-label={label} aria-pressed={active} onClick={onClick}
      className="flex items-center justify-center font-semibold transition-all duration-200 hover:scale-105 active:scale-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-700"
      style={{ minWidth: 44, height: 44, borderRadius: 12, paddingInline: 12, fontSize: 14, background: active ? (hc ? "#1a1a2e" : "#5b54e8") : (hc ? "rgba(0,0,0,0.07)" : "rgba(255,255,255,0.60)"), color: active ? "#ffffff" : (hc ? "#1a1a2e" : "#3d3b6e"), border: hc ? `2px solid ${active ? "#1a1a2e" : "#4a4870"}` : "1px solid rgba(255,255,255,0.75)", boxShadow: active && !hc ? "0 2px 10px rgba(91,84,232,0.30)" : "none" }}>
      {children}
    </button>
  );
}

/* ─── History panel ──────────────────────────────────────────── */
function HistoryPanel({ sessions, activeId, onSelect, onNew, onDelete, hc }: {
  sessions: Session[]; activeId: string; onSelect: (id: string) => void;
  onNew: () => void; onDelete: (id: string) => void; hc: boolean;
}) {
  const panelStyle: React.CSSProperties = hc
    ? { background: "#f5f4ff", border: "2px solid #1a1a2e", borderRadius: 24 }
    : { background: "rgba(255,255,255,0.32)", backdropFilter: "blur(28px)", WebkitBackdropFilter: "blur(28px)", border: "1px solid rgba(255,255,255,0.72)", borderRadius: 24, boxShadow: "0 8px 40px rgba(108,99,255,0.08), inset 0 1px 0 rgba(255,255,255,0.90)" };

  return (
    <aside aria-label="Riwayat percakapan" className="flex flex-col h-full shrink-0" style={{ width: "30%", minWidth: 200, maxWidth: 300, ...panelStyle }}>
      <div className="shrink-0 flex items-center justify-between px-4 py-4"
        style={{ borderBottom: hc ? "2px solid #1a1a2e" : "1px solid rgba(255,255,255,0.60)" }}>
        <div className="flex items-center gap-2">
          <MessageSquare size={14} style={{ color: hc ? "#1a1a2e" : "#6c63ff" }} />
          <span className="font-bold tracking-tight" style={{ fontSize: 13, color: hc ? "#0a0920" : "#1a1a2e" }}>Riwayat</span>
          <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full" style={{ background: hc ? "rgba(76,70,196,0.12)" : "rgba(108,99,255,0.10)", color: hc ? "#1a1a2e" : "#6c63ff" }}>{sessions.length}</span>
        </div>
        <button aria-label="Mulai percakapan baru" onClick={onNew}
          className="w-8 h-8 rounded-xl flex items-center justify-center transition-all hover:scale-105 active:scale-95"
          style={{ background: hc ? "#1a1a2e" : "#5b54e8", boxShadow: hc ? "none" : "0 2px 10px rgba(91,84,232,0.30)" }}>
          <Plus size={14} color="white" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto py-2 px-2 flex flex-col gap-1" style={{ scrollbarWidth: "none" }}>
        {sessions.length === 0 && (
          <div className="flex-1 flex flex-col items-center justify-center gap-2 opacity-40 py-10">
            <Clock size={22} style={{ color: hc ? "#1a1a2e" : "#6c63ff" }} />
            <p style={{ fontSize: 11, color: "#7b7a9d", textAlign: "center" }}>Belum ada riwayat</p>
          </div>
        )}
        {sessions.map(s => {
          const isActive = s.id === activeId;
          return (
            <div key={s.id}
              className="group relative flex items-start gap-2.5 px-3 py-2.5 rounded-xl cursor-pointer transition-all duration-150"
              style={{ background: isActive ? (hc ? "rgba(26,26,46,0.10)" : "rgba(108,99,255,0.12)") : "transparent", border: isActive ? (hc ? "1.5px solid #4a4870" : "1px solid rgba(108,99,255,0.22)") : "1px solid transparent" }}
              onClick={() => onSelect(s.id)}
            >
              <div className="shrink-0 w-7 h-7 rounded-lg flex items-center justify-center mt-0.5"
                style={{ background: isActive ? (hc ? "#1a1a2e" : "#5b54e8") : (hc ? "rgba(0,0,0,0.07)" : "rgba(108,99,255,0.10)") }}>
                <MessageSquare size={12} color={isActive ? "#ffffff" : hc ? "#1a1a2e" : "#6c63ff"} />
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-semibold truncate leading-snug" style={{ fontSize: 12, color: hc ? "#0a0920" : isActive ? "#1a1a2e" : "#3d3b6e" }}>{s.title}</p>
                <p className="mt-0.5" style={{ fontSize: 10, color: hc ? "#4a4870" : "#9896c8" }}>{relTime(s.timestamp)}</p>
              </div>
              <button aria-label={`Hapus sesi: ${s.title}`}
                onClick={e => { e.stopPropagation(); onDelete(s.id); }}
                className="shrink-0 w-6 h-6 rounded-lg flex items-center justify-center opacity-0 group-hover:opacity-100 transition-all"
                style={{ background: hc ? "rgba(0,0,0,0.07)" : "rgba(220,38,38,0.08)" }}>
                <Trash2 size={10} color={hc ? "#1a1a2e" : "#dc2626"} />
              </button>
            </div>
          );
        })}
      </div>

      <div className="shrink-0 px-4 py-3" style={{ borderTop: hc ? "2px solid #1a1a2e" : "1px solid rgba(255,255,255,0.55)" }}>
        <p style={{ fontSize: 10, color: hc ? "#4a4870" : "#9896c8", lineHeight: 1.5 }}>
          Sesi disimpan selama satu sesi browser.
        </p>
      </div>
    </aside>
  );
}

/* ─── App ────────────────────────────────────────────────────── */
export default function App() {
  // Seed once (lazy) from sessionStorage so navigating to /admin and back —
  // which remounts App — restores the chat instead of resetting to welcome.
  const [boot] = useState(() => {
    const restored = loadPersistedChat();
    if (restored) return restored;
    const s = makeSession(INITIAL);
    return { sessions: [s], activeId: s.id };
  });
  const [sessions, setSessions] = useState<Session[]>(boot.sessions);
  const [activeId, setActiveId] = useState(boot.activeId);
  const [input, setInput]       = useState("");
  const [typing, setTyping]     = useState(false);
  const [fontStep, setFontStep] = useState(1);
  const [hc, setHc]             = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const taRef  = useRef<HTMLTextAreaElement>(null);

  const fs = FONT_STEPS[fontStep];
  const messages = sessions.find(s => s.id === activeId)?.messages ?? INITIAL;

  const updateMsgs = useCallback((sid: string, fn: (p: Message[]) => Message[]) => {
    setSessions(prev => prev.map(s => s.id !== sid ? s : {
      ...s,
      messages: fn(s.messages),
      title: fn(s.messages).find(m => m.role === "user")?.text?.slice(0, 46) ?? s.title,
    }));
  }, []);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, typing]);

  // Persist chat so it survives the /admin round-trip (App remount) and reloads.
  useEffect(() => {
    try {
      sessionStorage.setItem(SESSION_STORE_KEY, JSON.stringify({ sessions, activeId }));
    } catch {
      /* storage full or unavailable — non-fatal, chat just won't persist */
    }
  }, [sessions, activeId]);

  const resolve = (text: string): Reply => REPLIES.find(r => r.match.test(text)) ?? FALLBACK;

  const send = useCallback(async (raw: string) => {
    const text = raw.trim();
    if (!text) return;
    const sid = activeId;
    setSessions(prev => prev.map(s => s.id !== sid ? s : {
      ...s,
      messages: [...s.messages, { id: `u${Date.now()}`, role: "user", text }],
      title: s.title === "Sesi baru" ? text.slice(0, 46) : s.title,
    }));
    setInput("");
    if (taRef.current) taRef.current.style.height = "auto";
    setTyping(true);

    try {
      // Real agent: hits POST /api/query → run_workflow() in app_web/server.py.
      const reply = await queryAgent(text);
      setTyping(false);
      const out: Message[] = [
        { id: `t${Date.now()}`, role: "assistant", text: reply.text },
      ];
      if (reply.books.length) {
        out.push({ id: `b${Date.now()}`, role: "assistant", books: reply.books, meta: reply.meta, trace: reply.trace });
      } else if (reply.trace.toolChain.length) {
        // No book cards but the agent still reasoned — attach the trace to the
        // text bubble so the thinking process stays visible.
        out[0].trace = reply.trace;
      }
      updateMsgs(sid, p => [...p, ...out]);
    } catch (err) {
      // Backend unreachable → fall back to the built-in demo replies so the
      // UI still works offline (e.g. before starting the FastAPI server).
      console.warn("Agent backend unavailable, using offline mock:", err);
      setTyping(false);
      const reply = resolve(text);
      const notice = "⚠️ Backend agen belum terhubung — menampilkan contoh offline.\n\n";
      updateMsgs(sid, p => [
        ...p,
        { id: `t${Date.now()}`, role: "assistant", text: notice + reply.text },
        { id: `b${Date.now()}`, role: "assistant", books: reply.books, meta: reply.meta },
      ]);
    }
  }, [activeId, updateMsgs]);

  const startNew = useCallback(() => {
    const s = makeSession();
    setSessions(p => [s, ...p]);
    setActiveId(s.id);
    setInput("");
  }, []);

  const deleteSession = useCallback((id: string) => {
    setSessions(prev => {
      const next = prev.filter(s => s.id !== id);
      if (next.length === 0) { const f = makeSession(); setActiveId(f.id); return [f]; }
      if (id === activeId) setActiveId(next[0].id);
      return next;
    });
  }, [activeId]);

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); }
  };

  const bgStyle: React.CSSProperties = hc ? { background: "#f0efff" } : {
    background: `
      radial-gradient(ellipse 70% 55% at 10% 10%, rgba(167,139,250,0.26) 0%, transparent 58%),
      radial-gradient(ellipse 55% 48% at 90% 5%,  rgba(196,181,253,0.18) 0%, transparent 52%),
      radial-gradient(ellipse 60% 52% at 65% 90%, rgba(147,197,253,0.18) 0%, transparent 52%),
      linear-gradient(140deg, #f3f1ff 0%, #ede9fe 28%, #e4e8ff 58%, #dbeafe 100%)
    `,
  };

  const glassPanel: React.CSSProperties = hc
    ? { background: "#ffffff", border: "2px solid #1a1a2e", borderRadius: 24, boxShadow: "none" }
    : { background: "rgba(255,255,255,0.38)", backdropFilter: "blur(32px)", WebkitBackdropFilter: "blur(32px)", border: "1px solid rgba(255,255,255,0.74)", borderRadius: 24, boxShadow: "0 8px 56px rgba(108,99,255,0.10), inset 0 1px 0 rgba(255,255,255,0.92)" };

  return (
    <div className="fixed inset-0 flex flex-col overflow-hidden" style={{ fontFamily: "'Inter', sans-serif", ...bgStyle }}>
      {!hc && <>
        <div className="absolute top-8 left-12 w-64 h-64 rounded-full pointer-events-none" style={{ background: "radial-gradient(circle,rgba(167,139,250,0.15) 0%,transparent 70%)", filter: "blur(20px)" }} />
        <div className="absolute bottom-16 right-10 w-80 h-80 rounded-full pointer-events-none" style={{ background: "radial-gradient(circle,rgba(147,197,253,0.13) 0%,transparent 70%)", filter: "blur(24px)" }} />
      </>}

      {/* ══ HEADER ══ */}
      <header role="banner" className="relative z-20 shrink-0 flex items-center justify-between px-5 md:px-8"
        style={{ height: 68, background: hc ? "#ffffff" : "rgba(255,255,255,0.52)", backdropFilter: hc ? "none" : "blur(28px)", WebkitBackdropFilter: hc ? "none" : "blur(28px)", borderBottom: hc ? "2px solid #1a1a2e" : "1px solid rgba(255,255,255,0.70)" }}>
        <div className="flex items-center gap-3 md:gap-4">
          <ImageWithFallback src={logoITS} alt="Institut Teknologi Sepuluh Nopember" className="h-10 w-auto object-contain" style={{ filter: hc ? "brightness(0)" : "brightness(0) opacity(0.80)" }} />
          <div className="shrink-0 w-px h-9" style={{ background: hc ? "#1a1a2e" : "rgba(90,88,128,0.25)" }} />
          <ImageWithFallback src={image_svgviewer_png_output_1} alt="Perpustakaan Jakarta" className="h-9 w-auto object-contain" style={{ filter: hc ? "brightness(0)" : "brightness(0) opacity(0.78)" }} />
          <div className="shrink-0 w-px h-9 hidden sm:block" style={{ background: hc ? "#1a1a2e" : "rgba(90,88,128,0.25)" }} />
          <div className="hidden sm:block">
            <p className="font-bold leading-tight tracking-tight" style={{ fontSize: 15, color: hc ? "#0a0920" : "#1a1a2e" }}>Agentic OPAC Explorer</p>
            <p className="font-medium" style={{ fontSize: 11, color: hc ? "#2d2b60" : "#7b7a9d", letterSpacing: "0.03em" }}>AI-powered library search</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5" role="toolbar" aria-label="Kontrol aksesibilitas">
          <A11yBtn label={hc ? "Nonaktifkan kontras tinggi" : "Aktifkan kontras tinggi"} onClick={() => setHc(v => !v)} active={hc} hc={hc}>
            {hc ? <Sun size={17} /> : <Moon size={17} />}
          </A11yBtn>
          <A11yBtn label="Perkecil teks" onClick={() => setFontStep(s => Math.max(0, s - 1))} active={false} hc={hc}>
            <span style={{ fontSize: 13 }}>A−</span>
          </A11yBtn>
          <A11yBtn label="Perbesar teks" onClick={() => setFontStep(s => Math.min(FONT_STEPS.length - 1, s + 1))} active={false} hc={hc}>
            <span style={{ fontSize: 16 }}>A+</span>
          </A11yBtn>
          <Link to="/admin" aria-label="Buka halaman admin"
            className="flex items-center justify-center transition-all duration-200 hover:scale-105 active:scale-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-700"
            style={{ minWidth: 44, height: 44, borderRadius: 12, paddingInline: 12, background: hc ? "rgba(0,0,0,0.07)" : "rgba(255,255,255,0.60)", color: hc ? "#1a1a2e" : "#3d3b6e", border: hc ? "2px solid #4a4870" : "1px solid rgba(255,255,255,0.75)" }}>
            <Settings size={17} />
          </Link>
        </div>
      </header>

      {/* ══ MAIN ══ */}
      <main role="main" className="flex-1 flex gap-3 px-3 py-3 md:px-5 md:py-4 overflow-hidden">
        <HistoryPanel sessions={sessions} activeId={activeId} onSelect={setActiveId} onNew={startNew} onDelete={deleteSession} hc={hc} />

        {/* Chat panel */}
        <div className="flex-1 flex flex-col min-w-0" style={glassPanel}>
          <div id="chat-log" role="log" aria-live="polite" className="flex-1 overflow-y-auto px-5 md:px-7 py-6 flex flex-col gap-5" style={{ scrollbarWidth: "none" }}>
            <style>{`#chat-log::-webkit-scrollbar{display:none} #qi::-webkit-scrollbar{display:none} #qi::placeholder{color:${hc?"#2d2b60":"#5a5880"};opacity:1}`}</style>

            {messages.map(msg =>
              msg.role === "user"
                ? <UserRow key={msg.id} text={msg.text!} fs={fs} hc={hc} />
                : <AiRow key={msg.id} msg={msg} fs={fs} hc={hc} />
            )}

            {typing && (
              <div className="flex gap-3 items-start">
                <div className="shrink-0 w-8 h-8 rounded-xl flex items-center justify-center mt-0.5" style={{ background: hc ? "#1a1a2e" : "linear-gradient(135deg,#6c63ff,#a78bfa)" }}>
                  <Sparkles size={15} color="white" />
                </div>
                <Dots hc={hc} />
              </div>
            )}
            <div ref={endRef} />
          </div>

          {/* Suggestions */}
          {messages.length === 1 && (
            <div className="shrink-0 px-5 md:px-7 pb-3 flex gap-2 flex-wrap">
              {SUGGESTIONS.map(s => (
                <button key={s} onClick={() => send(s)}
                  className="font-medium px-4 py-2 rounded-full transition-all hover:scale-[1.03] active:scale-[0.97]"
                  style={{ fontSize: fs - 3, background: hc ? "rgba(0,0,0,0.06)" : "rgba(108,99,255,0.08)", border: hc ? "1.5px solid #4a4870" : "1px solid rgba(108,99,255,0.22)", color: hc ? "#1a1a2e" : "#4c46c4", letterSpacing: "0.01em" }}>
                  {s}
                </button>
              ))}
            </div>
          )}

          <div className="shrink-0 mx-5 md:mx-7" style={{ height: 1, background: hc ? "rgba(26,26,46,0.18)" : "rgba(255,255,255,0.65)" }} />

          {/* Input */}
          <div className="shrink-0 px-4 md:px-6 py-4">
            <div className="flex items-end gap-3">
              <div className="flex-1 flex items-end rounded-2xl overflow-hidden"
                style={{ background: hc ? "#f5f4ff" : "rgba(255,255,255,0.82)", border: hc ? "2px solid #1a1a2e" : "1.5px solid rgba(108,99,255,0.28)", boxShadow: hc ? "none" : "0 2px 16px rgba(108,99,255,0.08)" }}>
                <textarea id="qi" ref={taRef} rows={1} value={input}
                  placeholder="Ketik kueri Anda di sini..."
                  aria-label="Masukkan kueri penelusuran buku"
                  onChange={e => { setInput(e.target.value); e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 130) + "px"; }}
                  onKeyDown={onKey}
                  className="flex-1 bg-transparent resize-none outline-none px-5 py-4"
                  style={{ fontSize: fs, lineHeight: 1.5, letterSpacing: "0.02em", color: hc ? "#0a0920" : "#0f0e1a", maxHeight: 130, scrollbarWidth: "none" }} />
              </div>
              <button onClick={() => send(input)} disabled={!input.trim() || typing} aria-label="Kirim kueri"
                className="shrink-0 flex items-center justify-center rounded-2xl transition-all duration-200 hover:scale-105 active:scale-95"
                style={{ width: 58, height: 58, background: !input.trim() || typing ? (hc ? "#c0bef0" : "rgba(108,99,255,0.22)") : (hc ? "#1a1a2e" : "#5b54e8"), boxShadow: input.trim() && !typing ? "0 4px 18px rgba(91,84,232,0.40)" : "none", cursor: !input.trim() || typing ? "not-allowed" : "pointer" }}>
                <Send size={22} color="white" strokeWidth={2} />
              </button>
            </div>
            <p className="text-center mt-2.5 select-none" style={{ fontSize: 12, color: hc ? "#4a4870" : "#8b89c0", letterSpacing: "0.03em" }}>
              Enter untuk kirim · Shift+Enter untuk baris baru
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}
