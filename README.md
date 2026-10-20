1. Şu an ne kurulu, bak:
bash
appium -v
appium driver list --installed
grep -h -E "appium@[0-9]|added|changed" ~/.npm/_logs/*.log 2>/dev/null | grep -i appium | tail -10
npm logları, bizden önce hangi Appium sürümünün kurulu olduğunu gösterebilir.

2. Eski sürümü geri kur. Eski sürüm Appium 3 idiyse ve logda belli bir sürüm görünmüyorsa:
bash
npm install -g appium@3
appium driver update xcuitest
appium driver update uiautomator2
Eski sürüm logda görünüyorsa, örneğin appium@2.11.5:
bash
npm install -g appium@2.11.5
Sürücüleri de mevcut Appium'a uygun sürüme çekmek gerekebilir. Bunu appium driver list --installed çıktısına göre söylerim.

3. Mevcut Appium'u yeniden başlat. Mac'i yeniden başlatmak da olur.

İlk komutların çıktısını yapıştır; tam olarak hangi sürüme döneceğimizi söyleyeyim.
