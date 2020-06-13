# Importación de las librerias utilizadas y funciones
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup
import smtplib
import email.message
import time
from datetime import datetime
import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
from credenciales import gmail_username, gmail_password, firebase_credentials


def scrapingCategoria(catComp, firebaseDB):
    for etiqueta in catComp:
        # Para cada categoría, accedemos a su enlace y obtenemos su título para hacer la consulta
        req = Request(etiqueta.get('href', None), headers={'User-Agent': 'Mozilla/5.0'})
        html = urlopen(req).read()
        soup=BeautifulSoup(html, 'html.parser')

        # Obtenemos el título
        titulo = soup.find(attrs={"class":"white-card h3"})
        titulo = titulo.text

        # También obtenemos el idFamilies ya que será necesario en las consultas
        # <input type="hidden" id="idQuery" data-key="idFamilies" value="6" />
        idFam = soup.find("input", attrs={"type":"hidden","data-key":"idFamilies"}).get('value', None)
        page = 0


        # Formamos el diccionario de parámetros de consulta
        d = {"page" : page, "order" : "relevance", "gtmTitle": titulo, "idFamilies[]" : idFam}

        while True:
            # Accedemos a la pagina i.
            # PcComponentes utiliza JavaScript con AJAX para ir haciendo sucesivas consultas mostrando
            # poco a poco los componentes.
            # Por ejemplo: https://www.pccomponentes.com/listado/ajax?page=1&order=relevance&gtmTitle=Procesadores%20Para%20El%20PC&idFamilies%5B%5D=4
            # tiene la página 1 de procesadores (dando a 'Ver Más' en la página habitual se mostrarían y asi sucesivamente con cada una)
            # (la página 0 es la que se muestra inicialmente)
            # así que hacemos manualmente las consultas Ajax y obtenemos la información desde el HTML de cada componente
            enlace = "https://www.pccomponentes.com/listado/ajax?" + urlencode(d, quote_via=quote)
            req = Request(enlace, headers={'User-Agent': 'Mozilla/5.0'})
            html = urlopen(req).read()
            soup=BeautifulSoup(html, 'html.parser')

            # Recuperamos cada componente (ver código HTML de la página)
            articulos = soup("article")

            # Si se ha llegado a una pagina que no tiene artículos, dejamos de ver
            if not articulos:
                break

            for articulo in articulos:
                # Para cada componente obtenemos su nombre, código y precio (ver HTML)
                nombreArt = articulo.get("data-name")
                codArt = articulo.get("data-id")
                precioArt = articulo.get("data-price")
                urlComp = "https://pccomponentes.com" + articulo.find(attrs={"GTM-productClick enlace-disimulado"}).get("href")
                

                
                ### si no hay componentes cargados tardara bastante!!! (2h aprox aunque puede variar)
                comp = firebaseDB.collection('componentes').document(codArt).get()
                img = ""
                if not comp.exists:
                    req = Request(urlComp, headers={'User-Agent': 'Mozilla/5.0'})
                    html = urlopen(req).read()
                    soup=BeautifulSoup(html, 'html.parser')
                    img = "https:" + soup.find(attrs={"item badgets-layer"})("a")[0].get("href")  
                else:
                    img = comp.get('img')
                firebaseDoc = firebaseDB.collection('componentes').document(codArt)
                firebaseDoc.set({
                        'nombre': nombreArt,
                        #'codigo': codArt,
                        'precio': float(precioArt),
                        'url': urlComp,
                        'categoria': d['gtmTitle'],
                        'img':img,
                        'valida':True
                        })

            d["page"] += 1


def mandaCorreo(e, comps, asunto):
    gmail_user = gmail_username
    gmail_password = gmail_password
    
    message_subject = asunto
    msg = '<br>'.join(['<img src="' + x[2] + '"alt="' + x[0] + '" width="100" height="100"><a href="' + x[1] + '">' + x[0] + '</a>' for x in comps])
    message_text = msg.encode('utf-8')

    msg = email.message.Message()
    msg['Subject'] = asunto
    msg['From'] = gmail_user
    msg['To'] = e
    msg.add_header('Content-Type','text/html')
    msg.set_payload(message_text)

    s = smtplib.SMTP('smtp.gmail.com', 587)
    s.ehlo()
    s.starttls()
    s.login(gmail_user, gmail_password)
    s.sendmail(msg['From'], msg['To'], msg.as_string())
    s.quit()
    
def dictNotifs(notifs, a, c, clave):
    if clave not in notifs.keys():
            notifs[clave] = list()
    notifs[clave].append((c.get('nombre'), c.get('url'), c.get('img')))
    

def notificaciones(firebaseDB):
    notifOfertasPush = dict()
    notifOfertasEmail = dict()
    notifElimsPush = dict()
    notifElimsEmail = dict()
    for u in firebaseDB.collection('usuarios').stream():
        for a in u.reference.collection('interes').stream():
            componente = firebaseDB.collection('componentes').document(a.id).get()
            if componente.get('valida') == False: # el componente ha sido eliminado
                if u.get('email'):
                    dictNotifs(notifElimsEmail, a, componente, u.id)
                if u.get('push'):
                    dictNotifs(notifElimsPush, a, componente, u.get('token'))
                a.reference.delete()
            elif a.get('precio') >= componente.get('precio'):
                if u.get('email'):
                    dictNotifs(notifOfertasEmail, a, componente, u.id)
                if u.get('push'):
                    dictNotifs(notifOfertasPush, a, componente, u.get('token'))
                
    for email, componentes in notifElimsEmail.items():
        # 'prueba@ucm.es' => [(comp1, url1), (comp5, url5), (comp7, url7)...]
        mandaCorreo(email, componentes, "[PcComponentes] Han desaparecido artículos que te interesaban")
        
    for email, componentes in notifOfertasEmail.items():
        mandaCorreo(email, componentes, "[PcComponentes] Han rebajado artículos que te interesan")
        
    for token, componentes in notifElimsPush.items():
        message = messaging.Message(
            notification=messaging.Notification(title='[PcComponentes]', body='Han desaparecido los componentes %s' % ', '.join([x[0] for x in componentes])),
            token=token
        )

        response = messaging.send(message)
        
    for token, componentes in notifOfertasPush.items():
        message = messaging.Message(
            notification=messaging.Notification(title='[PcComponentes]', body='Han rebajado componentes que te interesan'),
            token=token
        )

        response = messaging.send(message)

    # una vez se ha notificado tocaria borrar los articulos eliminados tanto de 'componentes' como de 'usuarios.interes'
    for d in firebaseDB.collection('componentes').where('valida', '==', False).stream():
        d.reference.delete()
        
           

def scraping(firebaseDB):
    # Entramos en la página de PcComponentes y sacamos el html
    req = Request('https://www.pccomponentes.com/componentes', headers={'User-Agent': 'Mozilla/5.0'})
    html = urlopen(req).read()
    soup=BeautifulSoup(html, 'html.parser')

    # Buscamos en el html de la página principal de componentes todos los enlaces que llevan a los tipos de componentes
    catComp = soup.find_all(attrs={"class":"enlace-secundario"})

    # Ponemos como no validos los componentes. Segun se vayan haciendo pasadas, si existen, se ponen
    # como validos. Si al final no son validos, quiere decir que es posible que hayan desaparecido asi que
    # se notificaria y se eliminarian de la base de datos
    
    
    for d in firebaseDB.collection('componentes').stream():
        firebaseDB.collection('componentes').document(d.id).update({'valida':False})

    # Entramos en cada categoría de componentes (procesadores, gráficas, placas base...)

    scrapingCategoria(catComp, firebaseDB)
    


    # Aqui se notificarian ofertas y que han desaparecido componentes (si es que han desaparecido) y se borrarian
    
    notificaciones(firebaseDB)

    

if __name__ == "__main__":
    start_time = time.time()
    
    if not firebase_admin._apps: 
        cred = credentials.Certificate(firebase_credentials)
        firebaseApp = firebase_admin.initialize_app(cred)

    firebaseDB = firestore.client()
    
    scraping(firebaseDB)

    f = open('timelog.txt', 'a')
    f.write("--- " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "--- " + str(round((time.time() - start_time)/60, 2)) + " minutos ---\n")
    f.close()
