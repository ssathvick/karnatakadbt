package io.mosip.esignet.config;
import java.net.URI;
import java.nio.file.*;
import java.util.*;
import org.springframework.context.annotation.*;
import org.springframework.beans.factory.config.BeanPostProcessor;
import org.springframework.web.client.RestTemplate;
import org.springframework.http.client.ClientHttpRequestInterceptor;
import org.springframework.http.client.support.HttpRequestWrapper;

/** Send service credentials only to the exact configured identity authority. */
@Configuration
public class NativeIdentityClientConfiguration {
 @Bean public static BeanPostProcessor nativeIdentityServiceAuthentication(){return new BeanPostProcessor(){
  public Object postProcessAfterInitialization(Object bean,String name){
   if(!(bean instanceof RestTemplate))return bean;
   Path folder=Paths.get("/run/kdbt-native-identity-client");
   if(!Files.isRegularFile(folder.resolve("authority")))return bean;
   try{
    URI target=URI.create(Files.readString(folder.resolve("authority")).trim());
    URI source=Files.isRegularFile(folder.resolve("source-authority"))?URI.create(Files.readString(folder.resolve("source-authority")).trim()):target;
    String prefix=Files.isRegularFile(folder.resolve("client-prefix"))?Files.readString(folder.resolve("client-prefix")).trim():"";
    String token=Files.readString(folder.resolve("service-token")).trim();
    if(!target.getScheme().equals("http")||target.getHost()==null||token.length()<40)throw new IllegalStateException("Invalid native identity authority");
    RestTemplate rest=(RestTemplate)bean;List<ClientHttpRequestInterceptor> chain=new ArrayList<>(rest.getInterceptors());
    chain.add((request,body,execution)->{
     URI uri=request.getURI();
     String path=uri.getRawPath();String client=path.substring(path.lastIndexOf('/')+1);
     if(Objects.equals(uri.getScheme(),source.getScheme())&&Objects.equals(uri.getHost(),source.getHost())&&uri.getPort()==source.getPort()&&path.startsWith("/v1/mock-identity-system/")&&client.startsWith(prefix)){
      request.getHeaders().setBearerAuth(token);
      final URI destination=target.resolve(uri.getRawPath()+(uri.getRawQuery()==null?"":"?"+uri.getRawQuery()));
      return execution.execute(new HttpRequestWrapper(request){public URI getURI(){return destination;}},body);
     }
     return execution.execute(request,body);
    });rest.setInterceptors(chain);return bean;
   }catch(Exception ex){throw new IllegalStateException("Native identity client authentication configuration failed",ex);}
  }
 };}
}
